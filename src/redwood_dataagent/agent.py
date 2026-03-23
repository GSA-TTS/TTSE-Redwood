from __future__ import annotations

"""Agent runtime entrypoints for the Redwood MVP foundation."""

from .config import AgentConfig
from .logging_utils import get_logger

# Create module logger (will auto-inject transfer_session_id from context)
LOGGER = get_logger("redwood_dataagent")


def _log_event(event: str, message: str) -> None:
    """
    Emit a structured audit-style log event for the current transfer session.

    Note: transfer_session_id is automatically injected from logging context.
    This eliminates manual session ID passing and enables automatic correlation.
    """
    # Log with event type - JsonFormatter will inject transfer_session_id automatically
    # via the contextvars context (no need to pass config around anymore)
    LOGGER.info(message, extra={"event": event})


def run_agent(config: AgentConfig) -> int:
    """Run the current foundation workflow for the configured agent mode."""
    # Pipeline start event (all logs now include transfer_session_id automatically)
    _log_event("pipeline_start", "Agent run started")

    # Route to appropriate workflow based on agent mode
    if config.agent_mode == "sender":
        # Sender and receiver execution paths are placeholders until the ADR flow is implemented.
        # Replace with real sender workflow
        _log_event("sender_placeholder", "Sender workflow placeholder executed")
    else:
        # Replace with real receiver workflow
        _log_event(
            "receiver_placeholder",
            "Receiver workflow placeholder executed",
        )

    # Pipeline completion event
    _log_event("pipeline_complete", "Agent run completed")
    return 0