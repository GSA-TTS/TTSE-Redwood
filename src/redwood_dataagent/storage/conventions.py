"""
Storage naming conventions and path builders for TTSE Redwood Data Agent.

This module implements the Day 1 storage convention patterns defined in the
MVP Implementation Plan. All storage references follow agency-prefixed,
environment-specific, purpose-defined naming to ensure clear operational
semantics and multi-tenant isolation.

Storage Pattern: tts-core-{environment}-{agency}-data-{purpose}

Supported purposes:
- staging: Sender-side artifact staging during transfer preparation
- landing: Receiver-side inbound landing zone from SFTP server
- target: Receiver-side final validated data storage

Path patterns:
- Sender incoming: incoming/
- Sender transfers: transfers/{transfer_session_id}/{file_name}
- Receiver extracted: extracted/{transfer_session_id}/{file_name}
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_BLANK_PATH_COMPONENT_MSG = "path component cannot be blank"


class StoragePurpose(str, Enum):
    """Storage purposes in the Day 1 transfer pipeline."""

    STAGING = "staging"
    """Sender-side staging bucket for initial artifacts."""

    LANDING = "landing"
    """Receiver-side landing zone for inbound transfers."""

    TARGET = "target"
    """Receiver-side final validated data storage."""


class SenderStoragePath(BaseModel):
    """Path builders for sender-side storage artifacts."""

    transfer_session_id: str = Field(
        ..., min_length=1, description="Correlation ID for one transfer"
    )
    file_name: str = Field(..., min_length=1, description="Artifact file name")

    @field_validator("transfer_session_id", "file_name")
    @classmethod
    def validate_path_components(cls, value: str) -> str:
        """Disallow blank path components after trimming whitespace."""
        if not value.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        return value

    @staticmethod
    def incoming_prefix() -> str:
        """Build sender incoming prefix for file detection scans."""
        return "incoming/"

    @staticmethod
    def transfers(transfer_session_id: str, file_name: str) -> str:
        """
        Build a transfer artifact path on sender storage.

        Pattern: transfers/{transfer_session_id}/{file_name}

        Args:
            transfer_session_id: Correlation ID for the transfer
            file_name: Name of the artifact (e.g., "data.tar.gz", "manifest.json")

        Returns:
            Path string for the artifact on sender staging storage

        Raises:
            ValueError: If transfer_session_id or file_name are blank

        Example:
            >>> SenderStoragePath.transfers("transfer-001", "data.tar.gz")
            "transfers/transfer-001/data.tar.gz"
        """
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not file_name or not file_name.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        
        return f"transfers/{transfer_session_id.strip()}/{file_name.strip()}"


class ReceiverStoragePath(BaseModel):
    """Path builders for receiver-side storage artifacts."""

    transfer_session_id: str = Field(
        ..., min_length=1, description="Correlation ID for one transfer"
    )
    file_name: str = Field(..., min_length=1, description="Artifact file name")

    @field_validator("transfer_session_id", "file_name")
    @classmethod
    def validate_path_components(cls, value: str) -> str:
        """Disallow blank path components after trimming whitespace."""
        if not value.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        return value

    @staticmethod
    def landing(transfer_session_id: str, file_name: str) -> str:
        """
        Build a landing zone path on receiver storage.

        Pattern: landing/{transfer_session_id}/{file_name}

        Receiver-side landing is the inbound zone where SFTP transfers arrive before
        validation and extraction.

        Args:
            transfer_session_id: Correlation ID for the transfer
            file_name: Name of the received artifact

        Returns:
            Path string for the artifact on receiver landing storage

        Raises:
            ValueError: If transfer_session_id or file_name are blank

        Example:
            >>> ReceiverStoragePath.landing("transfer-001", "data.tar.gz")
            "landing/transfer-001/data.tar.gz"
        """
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not file_name or not file_name.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        
        return f"landing/{transfer_session_id.strip()}/{file_name.strip()}"

    @staticmethod
    def extracted(transfer_session_id: str, file_name: str) -> str:
        """
        Build an extraction target path on receiver storage.

        Pattern: extracted/{transfer_session_id}/{file_name}

        Receiver-side extracted storage holds validated, decompressed data ready
        for downstream consumption.

        Args:
            transfer_session_id: Correlation ID for the transfer
            file_name: Name of the extracted artifact

        Returns:
            Path string for the artifact on receiver target storage

        Raises:
            ValueError: If transfer_session_id or file_name are blank

        Example:
            >>> ReceiverStoragePath.extracted("transfer-001", "records.csv")
            "extracted/transfer-001/records.csv"
        """
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not file_name or not file_name.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        
        return f"extracted/{transfer_session_id.strip()}/{file_name.strip()}"


def build_sender_bucket(
    agency: str, environment: str, purpose: StoragePurpose
) -> str:
    """
    Build a sender-side storage bucket name.

    Pattern: tts-core-{environment}-{agency}-data-{purpose}

    Sender storage is used by the source agency (e.g., DOT) to stage transfer
    artifacts before sending to the receiver.

    Args:
        agency: Source agency code (e.g., "dot", "faa")
        environment: Deployment environment (e.g., "dev", "staging", "prod")
        purpose: Storage purpose from StoragePurpose enum

    Returns:
        Fully-qualified bucket name following naming conventions

    Raises:
        ValueError: If agency, environment, or purpose are blank

    Example:
        >>> build_sender_bucket("dot", "dev", StoragePurpose.STAGING)
        "tts-core-dev-dot-data-staging"
    """
    if not agency.strip():
        raise ValueError("agency cannot be blank")
    if not environment.strip():
        raise ValueError("environment cannot be blank")

    return f"tts-core-{environment.strip().lower()}-{agency.strip().lower()}-data-{purpose.value}"


def build_receiver_bucket(
    agency: str, environment: str, purpose: Literal["landing", "target"]
) -> str:
    """
    Build a receiver-side storage bucket name.

    Pattern: tts-core-{environment}-{agency}-data-{purpose}

    Receiver storage (typically GSA) includes landing zones for inbound transfers
    and target storage for validated, extracted data.

    Args:
        agency: Receiver agency code (e.g., "gsa", "optic")
        environment: Deployment environment (e.g., "dev", "staging", "prod")
        purpose: Storage purpose - either "landing" or "target"

    Returns:
        Fully-qualified bucket name following naming conventions

    Raises:
        ValueError: If agency, environment, or purpose are blank/invalid

    Example:
        >>> build_receiver_bucket("gsa", "dev", "landing")
        "tts-core-dev-gsa-data-landing"
        
        >>> build_receiver_bucket("gsa", "prod", "target")
        "tts-core-prod-gsa-data-target"
    """
    if not agency.strip():
        raise ValueError("agency cannot be blank")
    if not environment.strip():
        raise ValueError("environment cannot be blank")
    
    purpose_lower = purpose.lower() if isinstance(purpose, str) else purpose
    if purpose_lower not in ("landing", "target"):
        raise ValueError('purpose must be either "landing" or "target"')

    return f"tts-core-{environment.strip().lower()}-{agency.strip().lower()}-data-{purpose_lower}"
