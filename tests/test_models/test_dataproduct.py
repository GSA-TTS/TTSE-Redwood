"""Unit tests for dataproduct typed models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from redwood_dataagent.models.dataproduct import DataproductDefinition


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_definition(filename: str) -> dict:
    definition_path = _repo_root() / "config" / "dataproducts" / "examples" / "definitions" / filename
    with definition_path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def test_dataproduct_definition_accepts_valid_example() -> None:
    """A committed example definition should validate as a typed model."""
    payload = _load_definition("dot_contract_extract_v1.json")

    definition = DataproductDefinition(
        dataproduct_id=payload["dataproduct_id"],
        version=payload["version"],
        status=payload["status"],
        payload=payload,
    )

    assert definition.dataproduct_id == "dot_contract_extract"
    assert definition.status.value == "active"
    assert definition.version == "1.0.0"
    assert definition.payload["extraction"]["source_type"] == "sql"


def test_dataproduct_definition_rejects_invalid_status() -> None:
    """Unknown status should fail typed model validation."""
    payload = _load_definition("dot_contract_extract_v1.json")
    payload["status"] = "invalid"

    with pytest.raises(ValidationError, match="status"):
        DataproductDefinition(
            dataproduct_id=payload["dataproduct_id"],
            version=payload["version"],
            status=payload["status"],
            payload=payload,
        )


def test_dataproduct_definition_rejects_missing_required_top_level_field() -> None:
    """Top-level required fields are still enforced by the typed model."""
    payload = _load_definition("dot_contract_extract_v1.json")
    payload.pop("dataproduct_id")

    with pytest.raises(KeyError, match="dataproduct_id"):
        DataproductDefinition(
            dataproduct_id=payload["dataproduct_id"],
            version=payload["version"],
            status=payload["status"],
            payload=payload,
        )
