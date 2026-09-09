"""In-memory job store for the Redwood Adapter API.

Tracks the lifecycle of outbound jobs dispatched by the Gateway.
Thread-safe for concurrent access by the HTTP server and sender workflow threads.

Job lifecycle:
    pending → running → sent      (success)
    pending → running → failed    (failure)
    pending → cancelled           (cancelled before running)
    running → cancelled           (cancelled while running)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {JobStatus.SENT, JobStatus.FAILED, JobStatus.CANCELLED}

_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.SENT, JobStatus.FAILED, JobStatus.CANCELLED},
}


@dataclass(frozen=True)
class JobResult:
    """Result metadata populated when a job reaches terminal sent status."""

    checksum_sha256: str
    file_size_bytes: int


@dataclass(frozen=True)
class Job:
    """Represents one accepted outbound job."""

    id: str
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    result: JobResult | None = None
    error: str | None = None

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class DuplicateJobError(Exception):
    """Raised when a job with the same ID already exists."""


class JobNotFoundError(Exception):
    """Raised when a requested job ID does not exist."""


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""


class JobStore:
    """Thread-safe in-memory store for adapter jobs.

    Supports one-at-a-time execution: only one job may be in
    pending or running state at any given time.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str) -> Job:
        """Create a new job in pending state.

        Raises:
            DuplicateJobError: If job_id already exists.
        """
        with self._lock:
            if job_id in self._jobs:
                raise DuplicateJobError(f"Job '{job_id}' already exists")
            job = Job(id=job_id)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> Job:
        """Return the job for the given ID.

        Raises:
            JobNotFoundError: If job_id does not exist.
        """
        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFoundError(f"Job '{job_id}' not found")
            return self._jobs[job_id]

    def transition(
        self,
        job_id: str,
        new_status: JobStatus,
        result: JobResult | None = None,
        error: str | None = None,
    ) -> Job:
        """Transition a job to a new status.

        Args:
            job_id: Job to update.
            new_status: Target status.
            result: Populated when transitioning to sent.
            error: Populated when transitioning to failed.

        Raises:
            JobNotFoundError: If job_id does not exist.
            InvalidTransitionError: If the transition is not allowed.
            ValueError: If transitioning to SENT without result, or FAILED without error.
        """
        if new_status == JobStatus.SENT and result is None:
            raise ValueError("Transitioning to SENT requires a JobResult")
        if new_status == JobStatus.FAILED and not error:
            raise ValueError("Transitioning to FAILED requires a non-empty error message")

        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFoundError(f"Job '{job_id}' not found")
            job = self._jobs[job_id]

            allowed = _ALLOWED_TRANSITIONS.get(job.status, set())
            if new_status not in allowed:
                raise InvalidTransitionError(
                    f"Cannot transition job '{job_id}' from '{job.status}' to '{new_status}'"
                )

            updated_job = cast(
                Job,
                replace(
                    job,
                    status=new_status,
                    updated_at=datetime.now(UTC),
                    result=result if result is not None else job.result,
                    error=error if error is not None else job.error,
                ),
            )
            self._jobs[job_id] = updated_job
            return updated_job

    def is_busy(self) -> bool:
        """Return True if any job is in pending or running state."""
        with self._lock:
            return any(
                j.status in {JobStatus.PENDING, JobStatus.RUNNING}
                for j in self._jobs.values()
            )

    def all_jobs(self) -> list[Job]:
        """Return a snapshot of all jobs (for testing/debugging)."""
        with self._lock:
            return list(self._jobs.values())


def make_job_store() -> JobStore:
    """Factory for creating a JobStore instance."""
    return JobStore()


# Module-level singleton used by the adapter HTTP server.
_store: JobStore | None = None


def get_job_store() -> JobStore:
    """Return the module-level JobStore singleton."""
    global _store
    if _store is None:
        _store = JobStore()
    return _store
