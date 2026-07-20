"""Typed runtime request model and validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from redwood_dataagent.exceptions import ConfigurationError
from redwood_dataagent.json_utils import load_json_object

JsonObject = dict[str, Any]
MetadataValue = str | int | float | bool


def _repo_root() -> Path:
    """Return the repository root path based on this module location."""
    return Path(__file__).resolve().parents[3]


def _default_schema_path() -> Path:
    """Return the default dataproduct request schema file path."""
    return _repo_root() / "config" / "dataproducts" / "schema" / "dataproduct-request.schema.json"


class DataproductRequest(BaseModel):
    """Normalized runtime request payload for dataproduct-driven workflows."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    dataproduct_id: str
    requesting_agency: str
    requested_by: str
    params: dict[str, Any]
    requested_row_limit: int | None = None
    requested_timeout_seconds: int | None = None
    delivery_target_id: str | None = None
    justification: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

    @field_validator("request_id", "requested_by", mode="before")
    @classmethod
    def _strip_required_strings(cls, value: Any) -> Any:
        """Trim whitespace for required string fields before validation."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("dataproduct_id", "requesting_agency", mode="before")
    @classmethod
    def _normalize_lowercase_strings(cls, value: Any) -> Any:
        """Trim and lowercase normalized identifier-like string fields."""
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("delivery_target_id", "justification", mode="before")
    @classmethod
    def _normalize_optional_strings(cls, value: Any) -> Any:
        """Trim optional strings and convert blank values to None."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped_value = value.strip()
            return stripped_value or None
        return value


def load_dataproduct_request(
    raw_request_json: str,
    schema_path: str | Path | None = None,
) -> DataproductRequest:
    """Load, schema-validate, and normalize one runtime request payload."""
    if not raw_request_json or not raw_request_json.strip():
        raise ConfigurationError("DATAPRODUCT_REQUEST_JSON is required and cannot be blank")

    payload = _load_request_payload(raw_request_json)
    normalized_payload = _normalize_payload_for_validation(payload)
    schema = _load_json_object(
        Path(schema_path) if schema_path is not None else _default_schema_path(),
        "Dataproduct request schema",
    )
    validator = Draft202012Validator(schema)
    _validate_payload_against_schema(normalized_payload, validator)

    try:
        return DataproductRequest.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc


def _load_request_payload(raw_request_json: str) -> JsonObject:
    """Parse raw request JSON and enforce an object payload."""
    try:
        payload = json.loads(raw_request_json)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"DATAPRODUCT_REQUEST_JSON must be valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError("DATAPRODUCT_REQUEST_JSON must be a JSON object")

    return payload


def _load_json_object(path: Path, label: str) -> JsonObject:
    """Load a JSON file and enforce an object root payload."""
    return load_json_object(path, label)


def _validate_payload_against_schema(payload: JsonObject, validator: Draft202012Validator) -> None:
    """Validate one request payload against the configured JSON schema."""
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    first_error = errors[0]
    path = ".".join(str(component) for component in first_error.path)
    path_text = path if path else "<root>"
    raise ConfigurationError(
        f"Schema validation failed for DATAPRODUCT_REQUEST_JSON at '{path_text}': {first_error.message}"
    )


def _normalize_payload_for_validation(payload: JsonObject) -> JsonObject:
    """Return a normalized payload copy for deterministic schema validation."""
    normalized_payload = dict(payload)

    for field_name in ("request_id", "requested_by"):
        value = normalized_payload.get(field_name)
        if isinstance(value, str):
            normalized_payload[field_name] = value.strip()

    for field_name in ("dataproduct_id", "requesting_agency"):
        value = normalized_payload.get(field_name)
        if isinstance(value, str):
            normalized_payload[field_name] = value.strip().lower()

    for field_name in ("delivery_target_id", "justification"):
        value = normalized_payload.get(field_name)
        if isinstance(value, str):
            stripped_value = value.strip()
            normalized_payload[field_name] = stripped_value or None

    return normalized_payload


def _format_validation_error(exc: ValidationError) -> str:
    """Convert Pydantic validation details into a concise config error."""
    first_error = exc.errors()[0]
    location = ".".join(str(part) for part in first_error["loc"])
    path_text = location or "<root>"
    return f"Invalid dataproduct request at '{path_text}': {first_error['msg']}"
