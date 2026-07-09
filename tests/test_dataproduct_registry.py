"""Unit tests for dataproduct registry loading and lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redwood_dataagent.dataproduct_registry import _build_definition, _load_json_object, load_dataproduct_registry
from redwood_dataagent.exceptions import ConfigurationError


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def schema_path(repo_root: Path) -> Path:
    return repo_root / "config" / "dataproducts" / "schema" / "dataproduct.schema.json"


@pytest.fixture
def definitions_dir(repo_root: Path) -> Path:
    return repo_root / "config" / "dataproducts" / "examples" / "definitions"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_dataproduct_registry_get_returns_active_definition(definitions_dir: Path, schema_path: Path) -> None:
    """Registry should load examples and return active definition by id."""
    registry = load_dataproduct_registry(definitions_dir, schema_path)

    dot_definition = registry.get("dot_contract_extract")

    assert dot_definition.dataproduct_id == "dot_contract_extract"
    assert dot_definition.status.value == "active"


def test_load_dataproduct_registry_prefers_highest_active_version(tmp_path: Path, schema_path: Path) -> None:
    """When multiple active versions exist, highest semantic version is selected."""
    base_payload = _load_json(
        Path(__file__).resolve().parents[1]
        / "config"
        / "dataproducts"
        / "examples"
        / "definitions"
        / "dot_contract_extract_v1.json"
    )

    v1_payload = dict(base_payload)
    v1_payload["version"] = "1.0.0"

    v2_payload = dict(base_payload)
    v2_payload["version"] = "1.1.0"

    _write_json(tmp_path / "dot_v1.json", v1_payload)
    _write_json(tmp_path / "dot_v2.json", v2_payload)

    registry = load_dataproduct_registry(tmp_path, schema_path)

    assert registry.get("dot_contract_extract").version == "1.1.0"


def test_load_dataproduct_registry_unknown_dataproduct_id_raises_key_error(definitions_dir: Path, schema_path: Path) -> None:
    """Unknown dataproduct ids should raise a clear KeyError."""
    registry = load_dataproduct_registry(definitions_dir, schema_path)

    with pytest.raises(KeyError, match="Unknown dataproduct_id"):
        registry.get("unknown_product")


def test_load_dataproduct_registry_invalid_definition_fails_fast(tmp_path: Path, schema_path: Path) -> None:
    """Schema-invalid definitions should fail load with filename in error."""
    payload = _load_json(
        Path(__file__).resolve().parents[1]
        / "config"
        / "dataproducts"
        / "examples"
        / "definitions"
        / "dot_contract_extract_v1.json"
    )
    payload.pop("dataproduct_id")
    invalid_file = tmp_path / "invalid_definition.json"
    _write_json(invalid_file, payload)

    with pytest.raises(ConfigurationError, match="invalid_definition.json"):
        load_dataproduct_registry(tmp_path, schema_path)


def test_load_dataproduct_registry_duplicate_id_version_fails_deterministically(tmp_path: Path, schema_path: Path) -> None:
    """Duplicate dataproduct_id/version combinations should fail with both files listed."""
    payload = _load_json(
        Path(__file__).resolve().parents[1]
        / "config"
        / "dataproducts"
        / "examples"
        / "definitions"
        / "dot_contract_extract_v1.json"
    )

    first_file = tmp_path / "a_first.json"
    second_file = tmp_path / "z_second.json"
    _write_json(first_file, payload)
    _write_json(second_file, payload)

    with pytest.raises(ConfigurationError, match="a_first.json") as exc_info:
        load_dataproduct_registry(tmp_path, schema_path)

    assert "z_second.json" in str(exc_info.value)


def test_load_dataproduct_registry_no_definition_files_raises(tmp_path: Path, schema_path: Path) -> None:
    """An empty definitions directory should fail with a clear error."""
    with pytest.raises(ConfigurationError, match="No dataproduct definition files found"):
        load_dataproduct_registry(tmp_path, schema_path)


def test_load_json_object_missing_file_raises(tmp_path: Path) -> None:
    """Missing JSON files should raise ConfigurationError."""
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ConfigurationError, match="file not found"):
        _load_json_object(missing_path, "Dataproduct definition")


def test_load_json_object_invalid_json_raises(tmp_path: Path) -> None:
    """Malformed JSON should raise ConfigurationError."""
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid JSON"):
        _load_json_object(invalid_path, "Dataproduct definition")


def test_load_json_object_non_object_raises(tmp_path: Path) -> None:
    """Non-object JSON payloads should be rejected."""
    array_path = tmp_path / "array.json"
    array_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must be a JSON object"):
        _load_json_object(array_path, "Dataproduct definition")


def test_build_definition_missing_required_key_raises(tmp_path: Path) -> None:
    """Missing key in payload should raise ConfigurationError from model builder."""
    incomplete_payload = {
        "dataproduct_id": "dot_contract_extract",
        "status": "active",
    }

    with pytest.raises(ConfigurationError, match="Missing required key 'version'"):
        _build_definition(incomplete_payload, tmp_path / "incomplete.json")
