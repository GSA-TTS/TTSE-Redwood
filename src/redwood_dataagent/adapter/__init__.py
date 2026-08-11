"""Adapter mode HTTP server for the Redwood Data Agent.

Exposes the Gateway/Adapter REST API defined in the FDE Node ADR.
Phase 1: health endpoint only. Job dispatch endpoints follow in subsequent stories.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Redwood Adapter API", version="1.0.0")


@app.get("/adapter/v1/health")
def health() -> dict[str, str]:
    """Return adapter liveness status."""
    return {"status": "ok"}
