"""Adapter mode HTTP server for the Redwood Data Agent.

Exposes the Gateway/Adapter REST API defined in the FDE Node ADR.
"""

from __future__ import annotations

from fastapi import FastAPI

from redwood_dataagent.adapter.outbound import router as outbound_router

app = FastAPI(title="Redwood Adapter API", version="1.0.0")

app.include_router(outbound_router)


@app.get("/adapter/v1/health")
def health() -> dict[str, str]:
    """Return adapter liveness status."""
    return {"status": "ok"}
