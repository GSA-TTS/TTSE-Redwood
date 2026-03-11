from __future__ import annotations

"""Environment-driven configuration for the Redwood Data Agent."""

import os
import uuid
from dataclasses import dataclass


VALID_AGENT_MODES = {"sender", "receiver"}


@dataclass(frozen=True)
class AgentConfig:
    """Normalized runtime settings for a single agent execution."""

    agent_mode: str
    tenant: str
    environment: str
    aws_region: str
    log_level: str
    transfer_session_id: str


def load_config() -> AgentConfig:
    """Build agent configuration from environment variables with sensible defaults."""
    agent_mode = os.getenv("AGENT_MODE", "receiver").strip().lower()
    if agent_mode not in VALID_AGENT_MODES:
        raise ValueError(
            f"AGENT_MODE must be one of {sorted(VALID_AGENT_MODES)}, got '{agent_mode}'"
        )

    # Every run gets a correlation identifier even when the caller does not supply one.
    transfer_session_id = os.getenv("TRANSFER_SESSION_ID") or str(uuid.uuid4())

    return AgentConfig(
        agent_mode=agent_mode,
        tenant=os.getenv("TENANT", "tts"),
        environment=os.getenv("ENVIRONMENT", "development"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        transfer_session_id=transfer_session_id,
    )