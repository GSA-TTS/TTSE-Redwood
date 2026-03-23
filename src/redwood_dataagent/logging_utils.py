from __future__ import annotations

"""Logging helpers for consistent JSON output with context tracking."""

import contextvars
import json
import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

# Context variable for transfer session ID (async-safe)
# Using contextvars ensures thread/async-safe tracking across concurrent operations.
# Each coroutine/thread gets its own session ID via the context.
_transfer_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "transfer_session_id", default=None
)

__all__ = [
    "JsonFormatter",
    "configure_logging",
    "set_transfer_session_id",
    "get_transfer_session_id",
    "logging_context",
    "get_logger",
    "_transfer_session_id",
]


class JsonFormatter(logging.Formatter):
    """Render log records as a compact JSON payload with context variables."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize standard and agent-specific fields into JSON."""
        # Build base payload with standard logging fields
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject transfer_session_id from context
        # This allows ALL logs to be traced back to their origin transfer session automatically
        session_id = _transfer_session_id.get()
        if session_id is not None:
            payload["transfer_session_id"] = session_id

        # Include custom event field if attached to record (e.g., "PIPELINE_START")
        # Events are optional and application-specific
        if hasattr(record, "event"):
            payload["event"] = record.event

        # Include any extra fields attached to the record (e.g., custom metadata)
        # This allows flexible extension without formatter changes
        if hasattr(record, "extra"):
            payload.update(record.extra)

        # Output as sorted JSON for consistency and easy log parsing/searching
        return json.dumps(payload, sort_keys=True)


def configure_logging(level: str) -> None:
    """Configure the root logger to emit JSON-formatted records."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        # Reuse existing handlers (tests and hosted environments often pre-configure handlers)
        # This prevents duplicate handlers while ensuring our formatter is applied
        for handler in root_logger.handlers:
            handler.setFormatter(JsonFormatter())
        return

    # If no handlers exist, create a default StreamHandler for stdout/stderr
    # This ensures logs always go somewhere
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def set_transfer_session_id(session_id: str) -> None:
    """
    Set the current transfer session ID in context.

    Args:
        session_id: Unique identifier for the transfer session.

    Use case: Call at pipeline start to track all logs for this transfer.
    """
    _transfer_session_id.set(session_id)


def get_transfer_session_id() -> Optional[str]:
    """
    Get the current transfer session ID from context.

    Returns:
        The current transfer session ID, or None if not set.
    """
    return _transfer_session_id.get()


@contextmanager
def logging_context(session_id: str) -> Generator[None, None, None]:
    """
    Context manager to temporarily override transfer_session_id.

    Args:
        session_id: Temporary transfer session ID for this scope.

    Example:
        with logging_context("temp-session-456"):
            logger.info("This will use temp-session-456")
        # Reverts to previous session ID
    """
    # Save the context token to restore previous value on exit
    # This enables nested contextvars usage with proper restoration
    token = _transfer_session_id.set(session_id)
    try:
        yield
    finally:
        # Reset to previous value (handles nested contexts correctly)
        # Even if exception occurs, previous context is restored
        _transfer_session_id.reset(token)


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__).

    Returns:
        A logging.Logger configured with module context.

    Note: Logger inherits root logger's JSON formatter automatically.
    """
    return logging.getLogger(name)