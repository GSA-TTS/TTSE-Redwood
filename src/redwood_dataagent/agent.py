from __future__ import annotations

"""Agent runtime entrypoints for the Redwood MVP foundation."""

import logging

from .config import AgentConfig


LOGGER = logging.getLogger("redwood_dataagent")


def _log_event(config: AgentConfig, event: str, message: str) -> None:
    """Emit a structured audit-style log event for the current transfer session."""
    LOGGER.info(
        message,
        extra={
            "event": event,
            "transfer_session_id": config.transfer_session_id,
        },
    )


def run_agent(config: AgentConfig) -> int:
    """Run the current foundation workflow for the configured agent mode."""
    _log_event(config, "pipeline_start", "Agent run started")

    if config.agent_mode == "sender":
        # Sender and receiver execution paths are placeholders until the ADR flow is implemented.
        _log_event(config, "sender_placeholder", "Sender workflow placeholder executed")
    else:
        _log_event(
            config,
            "receiver_placeholder",
            "Receiver workflow placeholder executed",
        )

    _log_event(config, "pipeline_complete", "Agent run completed")
    return 0