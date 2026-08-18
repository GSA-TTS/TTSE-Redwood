"""Unit tests for the outbound job dispatch endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from redwood_dataagent.adapter import app
from redwood_dataagent.adapter.job_store import JobStatus, JobStore


def make_client(store: JobStore) -> TestClient:
    """Return a TestClient with a fresh isolated job store."""
    with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store):
        return TestClient(app, raise_server_exceptions=False)


def make_store() -> JobStore:
    return JobStore()


class TestOutboundDispatch:
    def test_new_job_returns_202(self) -> None:
        """A new job dispatch returns 202 with job_id and pending status."""
        store = make_store()
        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client = TestClient(app)
            resp = client.put("/adapter/v1/outbound/job-1")

        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"] == "job-1"
        assert body["status"] == JobStatus.PENDING

    def test_duplicate_id_returns_409(self) -> None:
        """Re-dispatching a completed (terminal) job ID returns 409."""
        store = make_store()
        # Simulate a previously completed job so store is not busy
        store.create("job-1")
        store.transition("job-1", JobStatus.RUNNING)
        from redwood_dataagent.adapter.job_store import JobResult
        store.transition("job-1", JobStatus.SENT, result=JobResult("abc", 100))

        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client = TestClient(app)
            resp = client.put("/adapter/v1/outbound/job-1")

        assert resp.status_code == 409
        assert "already been accepted" in resp.json()["detail"]

    def test_busy_store_returns_429(self) -> None:
        """Returns 429 when another job is already in progress."""
        store = make_store()
        store.create("running-job")
        store.transition("running-job", JobStatus.RUNNING)

        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client = TestClient(app)
            resp = client.put("/adapter/v1/outbound/new-job")

        assert resp.status_code == 429
        assert "already in progress" in resp.json()["detail"]

    def test_accepted_job_is_stored_as_pending(self) -> None:
        """Accepted job is registered in the store with pending status."""
        store = make_store()
        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client = TestClient(app)
            client.put("/adapter/v1/outbound/job-abc")

        job = store.get("job-abc")
        assert job.status == JobStatus.PENDING

    def test_background_thread_is_started(self) -> None:
        """Sender workflow is triggered asynchronously after job is accepted."""
        store = make_store()
        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance
            client = TestClient(app)
            client.put("/adapter/v1/outbound/job-1")

        mock_instance.start.assert_called_once()

    def test_non_busy_pending_job_allows_new_dispatch(self) -> None:
        """A completed terminal job should not block new dispatches."""
        store = make_store()
        store.create("old-job")
        store.transition("old-job", JobStatus.RUNNING)
        from redwood_dataagent.adapter.job_store import JobResult
        store.transition("old-job", JobStatus.SENT, result=JobResult("abc", 100))

        with patch("redwood_dataagent.adapter.outbound.get_job_store", return_value=store), \
             patch("redwood_dataagent.adapter.outbound.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client = TestClient(app)
            resp = client.put("/adapter/v1/outbound/new-job")

        assert resp.status_code == 202
