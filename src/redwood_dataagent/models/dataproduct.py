"""Minimal dataproduct model used by the runtime registry."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataproductStatus(str, Enum):
    """Lifecycle status of a dataproduct definition."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class DataproductDefinition(BaseModel):
    """Minimal typed contract required by Story 1 loader/registry."""

    model_config = ConfigDict(extra="forbid")

    dataproduct_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    status: DataproductStatus

    # Full payload is kept for downstream consumers in later stories.
    payload: dict[str, Any]
