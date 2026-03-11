from __future__ import annotations

"""Logging helpers for consistent JSON output from the agent."""

import json
import logging
from typing import Any


class JsonFormatter(logging.Formatter):
    """Render log records as a compact JSON payload."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize standard and agent-specific fields into JSON."""
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "transfer_session_id"):
            payload["transfer_session_id"] = record.transfer_session_id

        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str) -> None:
    """Configure the root logger to emit JSON-formatted records."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        # Reuse existing handlers so the formatter can be applied in tests and hosted runtimes.
        for handler in root_logger.handlers:
            handler.setFormatter(JsonFormatter())
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)