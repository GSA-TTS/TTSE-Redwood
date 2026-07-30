"""Contract conformance tests for committed example files.

Validates every file under config/dataproducts/examples/ against its
canonical schema so CI fails fast when an example drifts from the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_DIR = _REPO_ROOT / "config" / "dataproducts" / "schema"
_EXAMPLES_DIR = _REPO_ROOT / "config" / "dataproducts" / "examples"

_DEFINITION_SCHEMA = json.loads((_SCHEMA_DIR / "dataproduct.schema.json").read_text(encoding="utf-8"))
_REQUEST_SCHEMA = json.loads((_SCHEMA_DIR / "dataproduct-request.schema.json").read_text(encoding="utf-8"))

_definition_files = sorted((_EXAMPLES_DIR / "definitions").glob("*.json"))
_request_files = sorted((_EXAMPLES_DIR / "requests").glob("*.json"))


@pytest.mark.parametrize("example_path", _definition_files, ids=[f.name for f in _definition_files])
def test_definition_example_conforms_to_schema(example_path: Path) -> None:
    """Each committed definition example must validate against dataproduct.schema.json."""
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(_DEFINITION_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, (
        f"{example_path.name} violates dataproduct.schema.json: "
        + "; ".join(f"[{'.'.join(str(p) for p in e.path) or '<root>'}] {e.message}" for e in errors)
    )


@pytest.mark.parametrize("example_path", _request_files, ids=[f.name for f in _request_files])
def test_request_example_conforms_to_schema(example_path: Path) -> None:
    """Each committed request example must validate against dataproduct-request.schema.json."""
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(_REQUEST_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, (
        f"{example_path.name} violates dataproduct-request.schema.json: "
        + "; ".join(f"[{'.'.join(str(p) for p in e.path) or '<root>'}] {e.message}" for e in errors)
    )
