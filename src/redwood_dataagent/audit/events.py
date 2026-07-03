"""
Audit event definitions for TTSE Redwood Data Agent.

This module defines the 11 Day 1 audit event types and the AuditEvent model.
These events enable end-to-end correlation and monitoring of transfers through
the pipeline from sender initiation through receiver completion.

Architecture note: Events are defined as Pydantic V2 models for type safety,
validation, and JSON serialization. This module contains ONLY event definitions,
not emission logic (see audit/logger.py or __init__.py for event emission).
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditEventType(str, Enum):
    """
    Enumeration of all Day 1 audit event types.

    Day 1 events cover the complete lifecycle from pipeline initiation through
    final storage. Events are organized chronologically and by pipeline stage:
    - PIPELINE_START: Sender initiates transfer
    - EXTRACT_DATA: Data extracted from source
    - POLICY_CHECK: Authorization/compliance check passes
    - COMPRESS: Extracted data compressed for transfer
    - MANIFEST_CREATED: Transfer manifest created (metadata + checksums)
    - SFTP_TRANSFER_START: Transfer to partner agency begins
    - SFTP_TRANSFER_COMPLETE: Transfer to partner agency completes
    - VALIDATE_MANIFEST: Receiver validates manifest integrity
    - DECOMPRESS: Receiver decompresses payload
    - STORE_DATA: Receiver stores in final location (S3)
    - PIPELINE_COMPLETE: Pipeline execution completes
    """

    PIPELINE_START = "pipeline_start"
    EXTRACT_DATA = "extract_data"
    POLICY_CHECK = "policy_check"
    COMPRESS = "compress"
    MANIFEST_CREATED = "manifest_created"
    SFTP_TRANSFER_START = "sftp_transfer_start"
    SFTP_TRANSFER_COMPLETE = "sftp_transfer_complete"
    VALIDATE_MANIFEST = "validate_manifest"
    DECOMPRESS = "decompress"
    STORE_DATA = "store_data"
    PIPELINE_COMPLETE = "pipeline_complete"


class EventOutcome(str, Enum):
    """
    Enumeration of event outcome states.

    All events must conclude with one of these outcomes to indicate
    success, partial success, or failure. Used for monitoring, alerting,
    and determining retry/escalation behavior.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"


class AuditEvent(BaseModel):
    """
    Structured audit event record for all pipeline operations.

    This Pydantic V2 model ensures consistent structure across all audit events,
    enabling reliable correlation, validation, and analysis. Each event captures:
    - What happened (event_type, outcome)
    - When it happened (timestamp)
    - Who is involved (sender_agency, receiver_agency)
    - Contextual details (destination_host, bytes_transferred, details dict)
    - Correlation metadata (transfer_session_id for end-to-end tracing)

    Attributes:
        event_type (AuditEventType): Type of event that occurred
        transfer_session_id (str): Unique identifier for end-to-end correlation;
                                   present on every event from pipeline start to complete
        timestamp (datetime): UTC timestamp when the event occurred
        sender_agency (str): Code of the sending agency (e.g., 'dot', 'gsa')
        receiver_agency (str): Code of the receiving agency
        stage (str): Pipeline stage name (e.g., 'sender', 'transfer', 'receiver')
        outcome (EventOutcome): Result of the operation (success, partial, failure)
        destination_host (Optional[str]): For transfer events, the partner SFTP server hostname
        bytes_transferred (Optional[int]): For transfer events, number of bytes successfully transferred
        details (Optional[Dict[str, Any]]): Additional context (e.g., file_count, checksum_algorithm, error_reason)
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "pipeline_start",
                "transfer_session_id": "transfer-20260317-001",
                "timestamp": "2026-03-17T12:30:45Z",
                "sender_agency": "dot",
                "receiver_agency": "gsa",
                "stage": "sender",
                "outcome": "success",
                "destination_host": None,
                "bytes_transferred": None,
                "details": {"agent_mode": "sender", "environment": "dev"},
            }
        }
    )

    event_type: AuditEventType = Field(..., description="Type of audit event")
    transfer_session_id: str = Field(..., min_length=1, description="Correlation ID for end-to-end tracing")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="UTC timestamp when event occurred"
    )
    sender_agency: str = Field(
        default="", description="Sending agency code (empty when receiver pod does not know the sender)"
    )
    receiver_agency: str = Field(
        default="", description="Receiving agency code (empty when sender pod does not know the receiver)"
    )
    stage: str = Field(..., description="Pipeline stage (sender, transfer, receiver)")
    outcome: EventOutcome = Field(..., description="Operation outcome")
    destination_host: str | None = Field(None, description="SFTP server hostname (transfer stage events)")
    bytes_transferred: int | None = Field(None, ge=0, description="Bytes transferred (transfer stage events)")
    details: dict[str, Any] | None = Field(None, description="Additional event context (extensible)")

    @field_validator("transfer_session_id")
    @classmethod
    def validate_transfer_session_id(cls, v: str) -> str:
        """Validate that transfer_session_id is non-empty."""
        if not v or not v.strip():
            raise ValueError("transfer_session_id cannot be empty")
        return v

    def to_structured_log(self) -> dict[str, Any]:
        """
        Convert audit event to structured logging format.

        Returns a dictionary suitable for JSON logging that includes all
        event fields in a flat structure. None values are included as-is
        to maintain consistent schema across logs.

        Returns:
            Dict[str, Any]: Event data ready for JSON serialization
        """
        return {
            "event_type": self.event_type.value,
            "transfer_session_id": self.transfer_session_id,
            "timestamp": self.timestamp.isoformat() + "Z",
            "sender_agency": self.sender_agency,
            "receiver_agency": self.receiver_agency,
            "stage": self.stage,
            "outcome": self.outcome.value,
            "destination_host": self.destination_host,
            "bytes_transferred": self.bytes_transferred,
            "details": self.details or {},
        }
