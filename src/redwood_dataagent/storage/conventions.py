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
- File mode scan prefix: file_mode/outgoing/
- File mode processed prefix: file_mode/processed/
- File mode transfers: file_mode/transfers/{transfer_session_id}/{file_name}
- Query mode outgoing prefix: query_mode/outgoing/
- Query mode processed prefix: query_mode/processed/
- Query mode transfers: query_mode/transfers/{transfer_session_id}/{file_name}
- Receiver landing: {sender_agency}/{transfer_session_id}/{file_name}
- Receiver extracted: extracted/{transfer_session_id}/{file_name}
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_BLANK_PATH_COMPONENT_MSG = "path component cannot be blank"
_TRANSFER_SESSION_ID_DESCRIPTION = "Correlation ID for one transfer"
_FILE_NAME_DESCRIPTION = "Artifact file name"
FILE_MODE_ROOT_PREFIX = "file_mode"
FILE_MODE_OUTGOING_PREFIX = f"{FILE_MODE_ROOT_PREFIX}/outgoing/"
FILE_MODE_PROCESSED_PREFIX = f"{FILE_MODE_ROOT_PREFIX}/processed/"
FILE_MODE_TRANSFERS_PREFIX = f"{FILE_MODE_ROOT_PREFIX}/transfers"
QUERY_MODE_ROOT_PREFIX = "query_mode"
QUERY_MODE_OUTGOING_PREFIX = f"{QUERY_MODE_ROOT_PREFIX}/outgoing/"
QUERY_MODE_PROCESSED_PREFIX = f"{QUERY_MODE_ROOT_PREFIX}/processed/"
QUERY_MODE_TRANSFERS_PREFIX = f"{QUERY_MODE_ROOT_PREFIX}/transfers"


class StoragePurpose(StrEnum):
    """Storage purposes in the Day 1 transfer pipeline."""

    STAGING = "staging"
    """Sender-side staging bucket for initial artifacts."""

    LANDING = "landing"
    """Receiver-side landing zone for inbound transfers."""

    TARGET = "target"
    """Receiver-side final validated data storage."""


class FileModeStoragePath(BaseModel):
    """Path builders for file-mode sender storage artifacts."""

    transfer_session_id: str = Field(..., min_length=1, description=_TRANSFER_SESSION_ID_DESCRIPTION)
    file_name: str = Field(..., min_length=1, description=_FILE_NAME_DESCRIPTION)

    @field_validator("transfer_session_id", "file_name")
    @classmethod
    def validate_path_components(cls, value: str) -> str:
        """Disallow blank path components after trimming whitespace."""
        if not value.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        return value

    @staticmethod
    def scan_prefix() -> str:
        """Build file-mode sender scan prefix for file detection scans."""
        return FILE_MODE_OUTGOING_PREFIX

    @staticmethod
    def processed_prefix() -> str:
        """Build file-mode sender processed prefix for idempotency markers."""
        return FILE_MODE_PROCESSED_PREFIX

    @staticmethod
    def transfers(transfer_session_id: str, file_name: str) -> str:
        """
        Build a transfer artifact path on file-mode sender storage.

        Pattern: file_mode/transfers/{transfer_session_id}/{file_name}

        Args:
            transfer_session_id: Correlation ID for the transfer
            file_name: Name of the artifact (e.g., "data.tar.gz", "manifest.json")

        Returns:
            Path string for the artifact on sender staging storage

        Raises:
            ValueError: If transfer_session_id or file_name are blank

        Example:
            >>> FileModeStoragePath.transfers("transfer-001", "data.tar.gz")
            "file_mode/transfers/transfer-001/data.tar.gz"
        """
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not file_name or not file_name.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        return f"{FILE_MODE_TRANSFERS_PREFIX}/{transfer_session_id.strip()}/{file_name.strip()}"

    @staticmethod
    def transfer_prefix(transfer_session_id: str) -> str:
        """Build file-mode transfer-session prefix on sender storage."""
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        return f"{FILE_MODE_TRANSFERS_PREFIX}/{transfer_session_id.strip()}/"


class QueryModeStoragePath(BaseModel):
    """Path builders for query-mode sender storage artifacts."""

    transfer_session_id: str = Field(..., min_length=1, description=_TRANSFER_SESSION_ID_DESCRIPTION)
    file_name: str = Field(..., min_length=1, description=_FILE_NAME_DESCRIPTION)

    @field_validator("transfer_session_id", "file_name")
    @classmethod
    def validate_path_components(cls, value: str) -> str:
        """Disallow blank path components after trimming whitespace."""
        if not value.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        return value

    @staticmethod
    def outgoing_prefix() -> str:
        """Build query-mode outgoing prefix for staged query results."""
        return QUERY_MODE_OUTGOING_PREFIX

    @staticmethod
    def processed_prefix() -> str:
        """Build query-mode processed prefix for query execution markers."""
        return QUERY_MODE_PROCESSED_PREFIX

    @staticmethod
    def processed_marker(template_id: str, fingerprint: str) -> str:
        """Build query-mode marker path for a successful query execution."""
        if not template_id or not template_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not fingerprint or not fingerprint.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        return f"{QUERY_MODE_PROCESSED_PREFIX}{template_id.strip()}/{fingerprint.strip()}.done"

    @staticmethod
    def transfers(transfer_session_id: str, file_name: str) -> str:
        """Build query-mode transfer artifact path on sender storage."""
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        if not file_name or not file_name.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        return f"{QUERY_MODE_TRANSFERS_PREFIX}/{transfer_session_id.strip()}/{file_name.strip()}"

    @staticmethod
    def transfer_prefix(transfer_session_id: str) -> str:
        """Build query-mode transfer-session prefix on sender storage."""
        if not transfer_session_id or not transfer_session_id.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        return f"{QUERY_MODE_TRANSFERS_PREFIX}/{transfer_session_id.strip()}/"


class ReceiverStoragePath(BaseModel):
    """Path builders for receiver-side storage artifacts."""

    transfer_session_id: str = Field(..., min_length=1, description=_TRANSFER_SESSION_ID_DESCRIPTION)
    file_name: str = Field(..., min_length=1, description=_FILE_NAME_DESCRIPTION)

    @field_validator("transfer_session_id", "file_name")
    @classmethod
    def validate_path_components(cls, value: str) -> str:
        """Disallow blank path components after trimming whitespace."""
        if not value.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)
        return value

    @staticmethod
    def landing(
        transfer_session_id: str,
        file_name: str,
        sender_agency: str | None = None,
    ) -> str:
        """
        Build a landing zone path on receiver storage.

        Pattern (legacy): landing/{transfer_session_id}/{file_name}
        Pattern (agency-scoped): {sender_agency}/{transfer_session_id}/{file_name}

        Receiver-side landing is the inbound zone where SFTP transfers arrive before
        validation and extraction.

        Args:
            transfer_session_id: Correlation ID for the transfer
            file_name: Name of the received artifact
            sender_agency: Optional sender agency prefix (e.g., "dot")

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

        if sender_agency is not None and not sender_agency.strip():
            raise ValueError(_BLANK_PATH_COMPONENT_MSG)

        transfer_session_id = transfer_session_id.strip()
        file_name = file_name.strip()

        if sender_agency is not None:
            sender_agency = sender_agency.strip()
            return f"{sender_agency}/{transfer_session_id}/{file_name}"

        return f"landing/{transfer_session_id}/{file_name}"

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


def build_sender_bucket(agency: str, environment: str, purpose: StoragePurpose) -> str:
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


def build_receiver_bucket(agency: str, environment: str, purpose: Literal["landing", "target"]) -> str:
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
