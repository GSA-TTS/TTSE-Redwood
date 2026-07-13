"""Unit tests for dataproduct request validation and normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from redwood_dataagent.exceptions import ConfigurationError
from redwood_dataagent.models.request import (
    DataproductRequest,
    _format_validation_error,
    _load_json_object,
    _load_request_payload,
    _normalize_payload_for_validation,
    load_dataproduct_request,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_request(filename: str) -> str:
    request_path = _repo_root() / "config" / "dataproducts" / "examples" / "requests" / filename
    return request_path.read_text(encoding="utf-8")


def test_load_dataproduct_request_accepts_valid_example() -> None:
    """Committed request examples should validate and normalize cleanly."""
    request = load_dataproduct_request(_load_request("sample-sender-request.json"))

    assert request.request_id == "REQ-20260706-0001"
    assert request.dataproduct_id == "dot_contract_extract"
    assert request.requesting_agency == "dot"
    assert request.requested_row_limit == 5000
    assert request.metadata == {}


def test_dataproduct_request_model_normalizes_case_and_whitespace() -> None:
    """Typed model should normalize common runtime formatting noise."""
    request = DataproductRequest.model_validate(
        {
            "request_id": "  REQ-123456  ",
            "dataproduct_id": "  DOT_CONTRACT_EXTRACT  ",
            "requesting_agency": "  DOT  ",
            "requested_by": "  analyst@dot.gov  ",
            "params": {"schema": "dot"},
            "delivery_target_id": "  target-1  ",
            "justification": "  monthly run  ",
        }
    )

    assert request.request_id == "REQ-123456"
    assert request.dataproduct_id == "dot_contract_extract"
    assert request.requesting_agency == "dot"
    assert request.requested_by == "analyst@dot.gov"
    assert request.delivery_target_id == "target-1"
    assert request.justification == "monthly run"


def test_load_dataproduct_request_missing_required_field_raises() -> None:
    """Schema failures should point to the missing contract field."""
    payload = json.loads(_load_request("sample-sender-request.json"))
    payload.pop("dataproduct_id")

    with pytest.raises(ConfigurationError, match="Schema validation failed"):
        load_dataproduct_request(json.dumps(payload))


def test_load_dataproduct_request_blank_requested_by_raises() -> None:
    """Whitespace-only required fields should fail after normalization."""
    payload = json.loads(_load_request("sample-sender-request.json"))
    payload["requested_by"] = "   "

    with pytest.raises(ConfigurationError, match="requested_by"):
        load_dataproduct_request(json.dumps(payload))


def test_load_dataproduct_request_blank_input_raises() -> None:
    """Blank request payloads should fail fast."""
    with pytest.raises(ConfigurationError, match="cannot be blank"):
        load_dataproduct_request("   ")


def test_load_request_payload_invalid_json_raises() -> None:
    """Malformed JSON should be rejected before validation."""
    with pytest.raises(ConfigurationError, match="must be valid JSON"):
        _load_request_payload("{bad-json")


def test_load_request_payload_non_object_raises() -> None:
    """Array payloads are not valid top-level request objects."""
    with pytest.raises(ConfigurationError, match="must be a JSON object"):
        _load_request_payload("[]")


def test_load_json_object_missing_file_raises(tmp_path: Path) -> None:
    """Missing schema files should raise ConfigurationError."""
    with pytest.raises(ConfigurationError, match="file not found"):
        _load_json_object(tmp_path / "missing.json", "Dataproduct request schema")


def test_load_json_object_invalid_json_raises(tmp_path: Path) -> None:
    """Invalid JSON files should raise ConfigurationError."""
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid JSON"):
        _load_json_object(invalid_path, "Dataproduct request schema")


def test_load_json_object_non_object_raises(tmp_path: Path) -> None:
    """Schema files must contain a JSON object."""
    invalid_path = tmp_path / "array.json"
    invalid_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must be a JSON object"):
        _load_json_object(invalid_path, "Dataproduct request schema")


def test_normalize_payload_for_validation_trims_and_lowercases() -> None:
    """Normalization should prepare a schema-friendly copy of the request payload."""
    normalized = _normalize_payload_for_validation(
        {
            "request_id": "  REQ-123456  ",
            "dataproduct_id": "  DOT_CONTRACT_EXTRACT  ",
            "requesting_agency": "  DOT  ",
            "requested_by": "  analyst@dot.gov  ",
            "delivery_target_id": "   ",
            "justification": "  monthly run  ",
        }
    )

    assert normalized["request_id"] == "REQ-123456"
    assert normalized["dataproduct_id"] == "dot_contract_extract"
    assert normalized["requesting_agency"] == "dot"
    assert normalized["requested_by"] == "analyst@dot.gov"
    assert normalized["delivery_target_id"] is None
    assert normalized["justification"] == "monthly run"


def test_format_validation_error_returns_first_location_message() -> None:
    """Validation errors should be reformatted into concise ConfigurationError text."""
    with pytest.raises(ValidationError) as exc_info:
        DataproductRequest.model_validate(
            {
                "request_id": "REQ-123456",
                "dataproduct_id": "valid_id",
                "requesting_agency": "aa",
                "requested_by": "ok",
                "params": [],
            }
        )

    message = _format_validation_error(exc_info.value)
    assert message.startswith("Invalid dataproduct request at '")
    assert "params" in message
