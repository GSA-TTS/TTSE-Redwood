"""Unit tests for the in-memory job store."""

from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError

import pytest

from redwood_dataagent.adapter.job_store import (
    DuplicateJobError,
    InvalidTransitionError,
    Job,
    JobNotFoundError,
    JobResult,
    JobStatus,
    JobStore,
)


def make_store() -> JobStore:
    return JobStore()


class TestJobStoreCreate:
    def test_create_returns_pending_job(self) -> None:
        store = make_store()
        job = store.create("job-1")
        assert job.id == "job-1"
        assert job.status == JobStatus.PENDING
        assert job.result is None
        assert job.error is None

    def test_create_duplicate_raises(self) -> None:
        store = make_store()
        store.create("job-1")
        with pytest.raises(DuplicateJobError):
            store.create("job-1")

    def test_create_different_ids_both_succeed(self) -> None:
        store = make_store()
        store.create("job-1")
        store.create("job-2")
        assert len(store.all_jobs()) == 2


class TestJobStoreGet:
    def test_get_returns_existing_job(self) -> None:
        store = make_store()
        store.create("job-1")
        job = store.get("job-1")
        assert job.id == "job-1"

    def test_get_unknown_id_raises(self) -> None:
        store = make_store()
        with pytest.raises(JobNotFoundError):
            store.get("does-not-exist")


class TestJobStoreTransition:
    def test_pending_to_running(self) -> None:
        store = make_store()
        store.create("job-1")
        job = store.transition("job-1", JobStatus.RUNNING)
        assert job.status == JobStatus.RUNNING

    def test_running_to_sent_with_result(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        result = JobResult(checksum_sha256="abc123", file_size_bytes=1024)
        job = store.transition("job-1", JobStatus.SENT, result=result)
        assert job.status == JobStatus.SENT
        assert job.result is not None
        assert job.result.checksum_sha256 == "abc123"
        assert job.result.file_size_bytes == 1024

    def test_running_to_failed_with_error(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        job = store.transition("job-1", JobStatus.FAILED, error="SFTP timeout")
        assert job.status == JobStatus.FAILED
        assert job.error == "SFTP timeout"

    def test_pending_to_cancelled(self) -> None:
        store = make_store()
        store.create("job-1")
        job = store.transition("job-1", JobStatus.CANCELLED)
        assert job.status == JobStatus.CANCELLED

    def test_running_to_cancelled(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        job = store.transition("job-1", JobStatus.CANCELLED)
        assert job.status == JobStatus.CANCELLED

    def test_sent_without_result_raises(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        with pytest.raises(ValueError, match="requires a JobResult"):
            store.transition("job-1", JobStatus.SENT)

    def test_failed_without_error_raises(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        with pytest.raises(ValueError, match="requires a non-empty error"):
            store.transition("job-1", JobStatus.FAILED)

    def test_invalid_transition_raises(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        store.transition("job-1", JobStatus.SENT, result=JobResult("abc", 100))
        with pytest.raises(InvalidTransitionError):
            store.transition("job-1", JobStatus.RUNNING)

    def test_transition_updates_updated_at(self) -> None:
        store = make_store()
        store.create("job-1")
        job_before = store.get("job-1")
        created_at = job_before.updated_at
        store.transition("job-1", JobStatus.RUNNING)
        job_after = store.get("job-1")
        assert job_after.updated_at >= created_at

    def test_transition_unknown_job_raises(self) -> None:
        store = make_store()
        with pytest.raises(JobNotFoundError):
            store.transition("missing", JobStatus.RUNNING)


class TestJobStoreIsBusy:
    def test_not_busy_when_empty(self) -> None:
        store = make_store()
        assert store.is_busy() is False

    def test_busy_when_job_is_pending(self) -> None:
        store = make_store()
        store.create("job-1")
        assert store.is_busy() is True

    def test_busy_when_job_is_running(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        assert store.is_busy() is True

    def test_not_busy_when_job_is_sent(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        store.transition("job-1", JobStatus.SENT, result=JobResult("abc", 100))
        assert store.is_busy() is False

    def test_not_busy_when_job_is_failed(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        store.transition("job-1", JobStatus.FAILED, error="oops")
        assert store.is_busy() is False

    def test_not_busy_when_job_is_cancelled(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.CANCELLED)
        assert store.is_busy() is False


class TestJobStoreThreadSafety:
    def test_concurrent_creates_only_one_succeeds(self) -> None:
        """Only one of two concurrent creates for the same ID should succeed."""
        store = make_store()
        errors: list[Exception] = []
        successes: list[Job] = []

        def try_create() -> None:
            try:
                job = store.create("shared-id")
                successes.append(job)
            except DuplicateJobError as e:
                errors.append(e)

        threads = [threading.Thread(target=try_create) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1
        assert len(errors) == 9

    def test_concurrent_transitions_are_consistent(self) -> None:
        """Concurrent transitions should not leave the job in an inconsistent state."""
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        sent_result = JobResult(checksum_sha256="abc123", file_size_bytes=100)

        results: list[str] = []

        def try_complete(status: JobStatus, label: str) -> None:
            try:
                store.transition(
                    "job-1",
                    status,
                    result=sent_result if status == JobStatus.SENT else None,
                    error="err" if status == JobStatus.FAILED else None,
                )
                results.append(label)
            except InvalidTransitionError:
                pass

        threads = [
            threading.Thread(target=try_complete, args=(JobStatus.SENT, "sent")),
            threading.Thread(target=try_complete, args=(JobStatus.FAILED, "failed")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one transition should have succeeded
        assert len(results) == 1
        job = store.get("job-1")
        assert job.status in {JobStatus.SENT, JobStatus.FAILED}


class TestJobStoreImmutability:
    def test_get_returns_immutable_job(self) -> None:
        store = make_store()
        store.create("job-1")

        client_view = store.get("job-1")
        with pytest.raises(FrozenInstanceError):
            client_view.status = JobStatus.SENT

        internal_view = store.get("job-1")
        assert internal_view.status == JobStatus.PENDING

    def test_all_jobs_returns_immutable_jobs(self) -> None:
        store = make_store()
        store.create("job-1")

        snapshot = store.all_jobs()
        with pytest.raises(FrozenInstanceError):
            snapshot[0].status = JobStatus.FAILED

        internal_view = store.get("job-1")
        assert internal_view.status == JobStatus.PENDING

    def test_result_payload_is_immutable(self) -> None:
        store = make_store()
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)

        result = JobResult(checksum_sha256="abc123", file_size_bytes=42)
        store.transition("job-1", JobStatus.SENT, result=result)
        with pytest.raises(FrozenInstanceError):
            result.file_size_bytes = 9999

        internal_view = store.get("job-1")
        assert internal_view.result is not None
        assert internal_view.result.file_size_bytes == 42
