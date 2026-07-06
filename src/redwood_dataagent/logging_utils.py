"""Logging helpers for consistent JSON output with context tracking."""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

# Context variable for transfer session ID (async-safe)
# Using contextvars ensures thread/async-safe tracking across concurrent operations.
# Each coroutine/thread gets its own session ID via the context.
_transfer_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("transfer_session_id", default=None)
_agent_mode: contextvars.ContextVar[str | None] = contextvars.ContextVar("agent_mode", default=None)

_STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}

__all__ = [
    "JsonFormatter",
    "configure_logging",
    "set_agent_mode",
    "get_agent_mode",
    "set_transfer_session_id",
    "get_transfer_session_id",
    "logging_context",
    "prefix_log_message",
    "get_logger",
    "_agent_mode",
    "_transfer_session_id",
]


_NOISY_LIBRARY_LOG_LEVELS: dict[str, int] = {
    # Paramiko emits transport/session chatter at INFO that lacks transfer context.
    # Keeping these at WARNING+ so only actionable issues are emitted.
    "paramiko": logging.WARNING,
    "paramiko.transport": logging.WARNING,
}


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

        agent_mode = _agent_mode.get()
        if agent_mode is not None:
            payload["agent_mode"] = agent_mode

        # Include custom event field if attached to record (e.g., "PIPELINE_START")
        # Events are optional and application-specific
        if hasattr(record, "event"):
            payload["event"] = record.event

        # Include any extra fields attached to the record (e.g., custom metadata)
        # This allows flexible extension without formatter changes
        if hasattr(record, "extra"):
            payload.update(record.extra)

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_FIELDS or key in payload or key == "extra":
                continue
            payload[key] = value

        # Output as sorted JSON for consistency and easy log parsing/searching
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(level: str) -> None:
    """Configure the root logger to emit JSON-formatted records."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for logger_name, logger_level in _NOISY_LIBRARY_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(logger_level)

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


def set_agent_mode(agent_mode: str | None) -> None:
    """Set the current agent mode in context."""
    _agent_mode.set(agent_mode)


def get_agent_mode() -> str | None:
    """Get the current agent mode from context."""
    return _agent_mode.get()


def set_transfer_session_id(session_id: str | None) -> None:
    """
    Set the current transfer session ID in context.

    Args:
        session_id: Unique identifier for the transfer session.

    Use case: Call at pipeline start to track all logs for this transfer.
    """
    _transfer_session_id.set(session_id)


def get_transfer_session_id() -> str | None:
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


def prefix_log_message(
    message: str,
    *,
    agent_mode: str | None = None,
    transfer_session_id: str | None = None,
) -> str:
    """Prefix a log message with agent mode and transfer session context."""
    parts: list[str] = []

    resolved_agent_mode = agent_mode or get_agent_mode()
    resolved_session_id = transfer_session_id or get_transfer_session_id()

    if resolved_agent_mode:
        parts.append(f"[{resolved_agent_mode}]")
    if resolved_session_id:
        parts.append(f"[{resolved_session_id}]")

    if not parts:
        return message

    return f"{''.join(parts)} {message}"


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
