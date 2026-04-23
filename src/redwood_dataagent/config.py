from __future__ import annotations

"""Environment-driven configuration for the Redwood Data Agent."""

import os
import uuid
from dataclasses import dataclass
from datetime import datetime

from .exceptions import ConfigurationError
from .storage.conventions import (
    SenderStoragePath,
    StoragePurpose,
    build_receiver_bucket,
    build_sender_bucket,
)


VALID_AGENT_MODES = {"sender", "receiver"}


@dataclass(frozen=True)
class AgentConfig:
    """Normalized runtime settings for a single agent execution.

    All bucket names are derived at load time from agency and environment values
    using the storage naming conventions, so callers never construct bucket names
    themselves.
    
    SFTP endpoints and credentials are loaded from environment variables and
    AWS Secrets Manager respectively.
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
    sender_data_directory: str
    sftp_endpoints: list[str]
    sftp_secrets_manager_name: str


def load_config() -> AgentConfig:
    """Build agent configuration from environment variables with sensible defaults.

    All required fields are validated at load time so that the agent fails fast
    with a clear :class:`~redwood_dataagent.exceptions.ConfigurationError` rather
    than raising obscure errors deep in the pipeline.

    Environment variables
    ---------------------
    AGENT_MODE
        ``"sender"`` or ``"receiver"``. Defaults to ``"receiver"``.
    AGENCY
        Agency code for this pod, e.g. ``"dot"`` or ``"gsa"``. When
        ``AGENT_MODE=sender`` this becomes the ``sender_agency``; when
        ``AGENT_MODE=receiver`` it becomes the ``receiver_agency``.
        **Required** — no default is applied.
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
    SFTP_ENDPOINTS
        Comma-separated list of SFTP endpoint(s).
        Examples:
        - Single on-prem: ``"10.10.20.15"``
        - Multi-AZ cloud: ``"10.0.1.50,10.0.2.50,10.0.3.50"``
        - DNS: ``"sftp.example.com"``
        - Multi-region DNS: ``"sftp-east.example.com,sftp-west.example.com"``
        **Required** — raises ``ConfigurationError`` if missing or blank.
    SFTP_SECRETS_MANAGER_NAME
        AWS Secrets Manager secret name containing SFTP credentials.
        Must have keys: ``user``, ``private-key``, ``public-key``.
        Auto-derived as ``{TENANT}-core-{ENVIRONMENT}-redwood-sftp-credentials``
        if not explicitly provided.

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

    agency = os.getenv("AGENCY", "").strip().lower()
    if not agency:
        raise ConfigurationError("AGENCY is required and cannot be blank")

    sender_agency = agency if agent_mode == "sender" else ""
    receiver_agency = agency if agent_mode == "receiver" else ""

    environment = os.getenv("ENVIRONMENT", "development").strip()
    if not environment:
        raise ConfigurationError("ENVIRONMENT cannot be blank")

    # Every run gets a correlation identifier even when the caller does not supply one.
    # Format: YYYYMMDD-HHMMSS-{uuid} for easy sorting and timestamp tracking
    if os.getenv("TRANSFER_SESSION_ID"):
        transfer_session_id = os.getenv("TRANSFER_SESSION_ID")
    else:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        session_uuid = str(uuid.uuid4())[:8]
        transfer_session_id = f"{timestamp}-{session_uuid}"

    # Parse SFTP endpoints (IPs or DNS names, comma-separated)
    sftp_endpoints_str = os.getenv("SFTP_ENDPOINTS", "").strip()
    if not sftp_endpoints_str:
        raise ConfigurationError("SFTP_ENDPOINTS is required and cannot be blank")
    
    raw_sftp_endpoints = sftp_endpoints_str.split(",")
    sftp_endpoints = [ep.strip() for ep in raw_sftp_endpoints]
    if any(not ep for ep in sftp_endpoints):
        raise ConfigurationError(
            f"SFTP_ENDPOINTS contains empty values (including whitespace-only entries): "
            f"{sftp_endpoints_str}"
        )

    # Determine SFTP Secrets Manager name
    tenant = os.getenv("TENANT", "tts")
    sftp_secrets_manager_name = os.getenv(
        "SFTP_SECRETS_MANAGER_NAME",
        f"{tenant}-core-{environment}-redwood-sftp-credentials"
    )

    if agent_mode == "sender":
        sender_staging_bucket = build_sender_bucket(
            sender_agency, environment, StoragePurpose.STAGING
        )
        sender_data_directory = (
            f"s3://{sender_staging_bucket}/{SenderStoragePath.incoming_prefix()}"
        )
        receiver_landing_bucket = ""
        receiver_target_bucket = ""
    else:  # receiver
        sender_staging_bucket = ""
        sender_data_directory = ""
        receiver_landing_bucket = build_receiver_bucket(
            receiver_agency, environment, "landing"
        )
        receiver_target_bucket = build_receiver_bucket(
            receiver_agency, environment, "target"
        )

    return AgentConfig(
        agent_mode=agent_mode,
        tenant=tenant,
        environment=environment,
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        sender_staging_bucket=sender_staging_bucket,
        receiver_landing_bucket=receiver_landing_bucket,
        receiver_target_bucket=receiver_target_bucket,
        sender_data_directory=sender_data_directory,
        sftp_endpoints=sftp_endpoints,
        sftp_secrets_manager_name=sftp_secrets_manager_name,
    )
