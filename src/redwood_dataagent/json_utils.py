"""Shared JSON loading helpers for contract/config files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .exceptions import ConfigurationError


def resolve_runtime_config_path(*relative_parts: str) -> Path:
    """Resolve a config path in both source and installed container layouts.

    Resolution order prefers explicit overrides, then the current working tree
    (for container/runtime layouts like ``/app/config``), and finally the local
    source checkout layout used in tests and development.
    """
    env_root = os.environ.get("REDWOOD_CONFIG_ROOT", "").strip()
    candidate_roots = []
    if env_root:
        candidate_roots.append(Path(env_root))

    candidate_roots.extend(
        [
            Path.cwd() / "config",
            Path(__file__).resolve().parents[2] / "config",
        ]
    )

    seen: set[Path] = set()
    for root in candidate_roots:
        resolved_root = root.resolve()
        if resolved_root in seen:
            continue
        seen.add(resolved_root)

        candidate = resolved_root.joinpath(*relative_parts)
        if candidate.exists():
            return candidate

    searched_roots = ", ".join(str(path) for path in seen)
    raise ConfigurationError(
        "Runtime config path not found for "
        f"'{Path(*relative_parts)}'. Searched roots: {searched_roots}"
    )


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
