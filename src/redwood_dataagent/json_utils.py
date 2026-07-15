"""Shared JSON loading helpers for contract/config files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .exceptions import ConfigurationError


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load a JSON file and enforce an object root payload."""
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{label} file not found: '{path}'") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{label} file is invalid JSON: '{path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(f"{label} must be a JSON object: '{path}'")

    return payload
