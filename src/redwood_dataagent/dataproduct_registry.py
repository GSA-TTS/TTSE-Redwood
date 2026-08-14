"""Runtime loader and registry for dataproduct definitions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from packaging.version import Version

from .exceptions import ConfigurationError
from .json_utils import load_json_object
from .models.dataproduct import DataproductDefinition, DataproductStatus

DefinitionKey = tuple[str, str]
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class DataproductRegistry:
    """In-memory runtime registry keyed by dataproduct_id."""

    definitions_by_id: dict[str, DataproductDefinition]
    definitions_by_id_and_version: dict[DefinitionKey, DataproductDefinition]

    def get(self, dataproduct_id: str) -> DataproductDefinition:
        """Return the selected active definition for a dataproduct id."""
        normalized_id = dataproduct_id.strip().lower()
        try:
            return self.definitions_by_id[normalized_id]
        except KeyError as exc:
            raise KeyError(f"Unknown dataproduct_id '{dataproduct_id}'") from exc


def load_dataproduct_registry(definitions_dir: str | Path, schema_path: str | Path) -> DataproductRegistry:
    """Load, validate, and index dataproduct definitions from disk."""
    schema = _load_json_object(Path(schema_path), "Dataproduct schema")
    validator = Draft202012Validator(schema)

    definition_paths = sorted(Path(definitions_dir).glob("*.json"))
    if not definition_paths:
        raise ConfigurationError(f"No dataproduct definition files found in '{definitions_dir}'")

    all_definitions: dict[DefinitionKey, DataproductDefinition] = {}
    loaded_from: dict[DefinitionKey, Path] = {}
    grouped_by_id: defaultdict[str, list[DataproductDefinition]] = defaultdict(list)

    for definition_path in definition_paths:
        payload = _load_json_object(definition_path, "Dataproduct definition")
        _validate_payload_against_schema(payload, validator, definition_path)

        definition = _build_definition(payload, definition_path)

        key: DefinitionKey = (definition.dataproduct_id, definition.version)
        if key in all_definitions:
            first_file = loaded_from[key]
            raise ConfigurationError(
                "Duplicate dataproduct_id/version combination "
                f"'{definition.dataproduct_id}/{definition.version}' found in "
                f"'{first_file}' and '{definition_path}'"
            )

        all_definitions[key] = definition
        loaded_from[key] = definition_path
        grouped_by_id[definition.dataproduct_id].append(definition)

    selected_definitions = {
        dataproduct_id: _select_active_definition(definitions)
        for dataproduct_id, definitions in grouped_by_id.items()
    }

    return DataproductRegistry(
        definitions_by_id=selected_definitions,
        definitions_by_id_and_version=all_definitions,
    )


def _load_json_object(path: Path, label: str) -> dict:
    """Load and validate one JSON object file."""
    return load_json_object(path, label)


def _build_definition(payload: JsonObject, definition_path: Path) -> DataproductDefinition:
    """Build minimal dataproduct model from a schema-validated payload."""
    try:
        return DataproductDefinition(
            dataproduct_id=payload["dataproduct_id"],
            version=payload["version"],
            status=payload["status"],
            payload=payload,
        )
    except KeyError as exc:
        raise ConfigurationError(f"Missing required key '{exc.args[0]}' in '{definition_path}'") from exc


def _validate_payload_against_schema(payload: dict, validator: Draft202012Validator, definition_path: Path) -> None:
    """Validate one payload against the canonical dataproduct schema."""
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if not errors:
        return

    first_error = errors[0]
    path = ".".join(str(component) for component in first_error.path)
    path_text = path if path else "<root>"

    raise ConfigurationError(
        f"Schema validation failed for '{definition_path}' at '{path_text}': {first_error.message}"
    )


def _select_active_definition(definitions: list[DataproductDefinition]) -> DataproductDefinition:
    """Select the deterministic runtime definition for a dataproduct id.

    Preference order:
    1. Highest semantic version among active definitions.
    2. If no active definitions exist, highest semantic version overall.
    """
    active_definitions = [definition for definition in definitions if definition.status == DataproductStatus.ACTIVE]
    candidates = active_definitions if active_definitions else definitions

    return max(candidates, key=lambda definition: _normalize_semver(definition.version))


def _normalize_semver(version: str) -> Version:
    """Normalize v-prefixed versions for consistent semantic sorting."""
    return Version(version[1:] if version.startswith("v") else version)
