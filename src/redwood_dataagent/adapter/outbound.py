"""Outbound job dispatch router for the Redwood Adapter API.

Handles Gateway-initiated outbound transfer requests.
"""

from __future__ import annotations

import threading
from http import HTTPStatus

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from redwood_dataagent.adapter.job_store import (
    DuplicateJobError,
    InvalidTransitionError,
    JobNotFoundError,
    JobStatus,
    get_job_store,
)

router = APIRouter()


def _serialize_job(job_id: str) -> dict[str, object]:
    """Return a JSON-ready representation of one adapter job."""
    store = get_job_store()
    job = store.get(job_id)

    payload: dict[str, object] = {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }
    if job.result is not None:
        payload["result"] = {
            "checksum_sha256": job.result.checksum_sha256,
            "file_size_bytes": job.result.file_size_bytes,
        }
    if job.error is not None:
        payload["error"] = job.error
    return payload


def _run_sender(job_id: str) -> None:
    """Execute the sender workflow in a background thread and update job state."""
    store = get_job_store()
    try:
        from redwood_dataagent.adapter.job_store import JobResult
        from redwood_dataagent.agent import DEFAULT_ARCHIVE_FILE_NAME, SenderTransferArtifacts, run_agent
        from redwood_dataagent.config import load_config

        store.transition(job_id, JobStatus.RUNNING)

        config = load_config()
        job_result: JobResult | None = None

        def capture_result(artifacts: SenderTransferArtifacts) -> None:
            nonlocal job_result
            archive_file = next(
                manifest_file for manifest_file in artifacts.manifest.files
                if manifest_file.file_name == DEFAULT_ARCHIVE_FILE_NAME
            )
            job_result = JobResult(
                checksum_sha256=archive_file.checksum_sha256,
                file_size_bytes=archive_file.file_size_bytes,
            )

        result_code = run_agent(config, on_sender_success=capture_result)

        if result_code == 0:
            result = job_result or JobResult(checksum_sha256="", file_size_bytes=0)
            store.transition(job_id, JobStatus.SENT, result=result)
        else:
            store.transition(job_id, JobStatus.FAILED, error=f"Sender exited with code {result_code}")

    except Exception as exc:  # noqa: BLE001
        try:
            store.transition(job_id, JobStatus.FAILED, error=str(exc))
        except Exception:  # noqa: BLE001
            pass


@router.put("/adapter/v1/outbound/{job_id}", status_code=HTTPStatus.ACCEPTED)
def dispatch_outbound_job(job_id: str) -> JSONResponse:
    """Accept an outbound job request from the Gateway.

    Returns:
        202 Accepted  — job registered and sender workflow started.
        409 Conflict  — job ID already accepted.
        429 Too Many Requests — another job is already in progress.
    """
    store = get_job_store()

    if store.is_busy():
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content={"detail": "A job is already in progress. Only one job at a time is supported."},
        )

    try:
        store.create(job_id)
    except DuplicateJobError:
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT,
            content={"detail": f"Job '{job_id}' has already been accepted."},
        )

    thread = threading.Thread(target=_run_sender, args=(job_id,), daemon=True)
    thread.start()

    return JSONResponse(
        status_code=HTTPStatus.ACCEPTED,
        content={"job_id": job_id, "status": JobStatus.PENDING},
    )


@router.get("/adapter/v1/outbound/{job_id}")
def get_outbound_job_status(job_id: str) -> JSONResponse:
    """Return current state for one outbound job.

    Returns:
        200 OK     — job exists; current status payload returned.
        404 Not Found — unknown job ID.
    """
    try:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=_serialize_job(job_id),
        )
    except JobNotFoundError:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": f"Job '{job_id}' not found."},
        )


@router.delete("/adapter/v1/outbound/{job_id}")
def cancel_outbound_job(job_id: str) -> JSONResponse:
    """Cancel one outbound job.

    Returns:
        200 OK          — job was pending/running and is now cancelled.
        404 Not Found   — unknown job ID.
        409 Conflict    — job is already terminal and cannot be cancelled.
    """
    store = get_job_store()

    try:
        store.transition(job_id, JobStatus.CANCELLED)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=_serialize_job(job_id),
        )
    except JobNotFoundError:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": f"Job '{job_id}' not found."},
        )
    except InvalidTransitionError:
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT,
            content={"detail": f"Job '{job_id}' is already terminal and cannot be cancelled."},
        )
