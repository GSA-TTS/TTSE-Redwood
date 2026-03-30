from __future__ import annotations

"""Environment-driven configuration for the Redwood Data Agent."""

import os
import uuid
from dataclasses import dataclass

from .exceptions import ConfigurationError
from .storage.conventions import StoragePurpose, build_receiver_bucket, build_sender_bucket


VALID_AGENT_MODES = {"sender", "receiver"}


@dataclass(frozen=True)
class AgentConfig:
    """Normalized runtime settings for a single agent execution.

    All bucket names are derived at load time from agency and environment values
    using the storage naming conventions, so callers never construct bucket names
    themselves.
    """

    agent_mode: str
    tenant: str
    environment: str
    aws_region: str
    log_level: str
    transfer_session_id: str
    sender_agency: str
    receiver_agency: str
    sender_staging_bucket: str
    receiver_landing_bucket: str
    receiver_target_bucket: str


def load_config() -> AgentConfig:
    """Build agent configuration from environment variables with sensible defaults.

    All required fields are validated at load time so that the agent fails fast
    with a clear :class:`~redwood_dataagent.exceptions.ConfigurationError` rather
    than raising obscure errors deep in the pipeline.

    Environment variables
    ---------------------
    AGENT_MODE
        ``"sender"`` or ``"receiver"``. Defaults to ``"receiver"``.
    SENDER_AGENCY
        Source agency code, e.g. ``"dot"``. Defaults to ``"dot"``.
    RECEIVER_AGENCY
        Destination agency code, e.g. ``"gsa"``. Defaults to ``"gsa"``.
    TENANT
        Organisational tenant identifier. Defaults to ``"tts"``.
    ENVIRONMENT
        Deployment environment, e.g. ``"dev"``, ``"staging"``, ``"prod"``.
        Defaults to ``"development"``.
    AWS_REGION
        AWS region for SDK calls. Defaults to ``"us-east-1"``.
    LOG_LEVEL
        Python logging level string. Defaults to ``"INFO"``.
    TRANSFER_SESSION_ID
        Correlation ID for the current transfer run. Auto-generated when absent.

    Returns
    -------
    AgentConfig
        Fully validated, immutable configuration object.

    Raises
    ------
    ConfigurationError
        If any required environment variable holds an invalid or blank value.
    """
    agent_mode = os.getenv("AGENT_MODE", "receiver").strip().lower()
    if agent_mode not in VALID_AGENT_MODES:
        raise ConfigurationError(
            f"AGENT_MODE must be one of {sorted(VALID_AGENT_MODES)}, got '{agent_mode}'"
        )

    sender_agency = os.getenv("SENDER_AGENCY", "dot").strip().lower()
    if not sender_agency:
        raise ConfigurationError("SENDER_AGENCY cannot be blank")

    receiver_agency = os.getenv("RECEIVER_AGENCY", "gsa").strip().lower()
    if not receiver_agency:
        raise ConfigurationError("RECEIVER_AGENCY cannot be blank")

    environment = os.getenv("ENVIRONMENT", "development").strip()
    if not environment:
        raise ConfigurationError("ENVIRONMENT cannot be blank")

    # Every run gets a correlation identifier even when the caller does not supply one.
    transfer_session_id = os.getenv("TRANSFER_SESSION_ID") or str(uuid.uuid4())

    return AgentConfig(
        agent_mode=agent_mode,
        tenant=os.getenv("TENANT", "tts"),
        environment=environment,
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        sender_staging_bucket=build_sender_bucket(
            sender_agency, environment, StoragePurpose.STAGING
        ),
        receiver_landing_bucket=build_receiver_bucket(
            receiver_agency, environment, "landing"
        ),
        receiver_target_bucket=build_receiver_bucket(
            receiver_agency, environment, "target"
        ),
    )