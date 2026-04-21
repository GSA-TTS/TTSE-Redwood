"""
Audit event logging for TTSE Redwood Data Agent.

This module provides structured audit event emission with automatic context
tracking and JSON logging integration. All audit events are timestamped in UTC
and include transfer_session_id for end-to-end correlation.

Architecture:
- log_event(): Core function for emitting audit events
- Convenience helpers for common pipeline stages (log_pipeline_start, etc.)
- Integration with logging infrastructure (transfer_session_id via contextvars)
- Pydantic validation ensures type safety and schema consistency

Example usage:
    from redwood_dataagent.audit.logger import (
        log_pipeline_start,
        log_extract_data,
        log_pipeline_complete,
    )
    from redwood_dataagent.audit.events import EventOutcome

    # Emit pipeline start event
    log_pipeline_start(
        transfer_session_id="transfer-20260317-001",
        sender_agency="dot",
        receiver_agency="gsa",
    )

    # Emit extract data event with details
    log_extract_data(
        transfer_session_id="transfer-20260317-001",
        sender_agency="dot",
        receiver_agency="gsa",
        outcome=EventOutcome.SUCCESS,
        details={"file_count": 42, "total_bytes": 1_048_576},
    )

    # Emit pipeline complete event
    log_pipeline_complete(
        transfer_session_id="transfer-20260317-001",
        sender_agency="dot",
        receiver_agency="gsa",
        outcome=EventOutcome.SUCCESS,
    )
"""

from typing import Any, Dict, Optional

from redwood_dataagent.audit.events import (
    AuditEvent,
    AuditEventType,
    EventOutcome,
)
from redwood_dataagent.logging_utils import (
    get_logger,
    get_transfer_session_id,
    prefix_log_message,
)

# Module logger for audit event emission
_logger = get_logger(__name__)


def log_event(
    event_type: AuditEventType,
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    stage: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    destination_host: Optional[str] = None,
    bytes_transferred: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Emit a structured audit event via JSON logging.

    This is the core audit event emission function. It creates an AuditEvent
    instance, validates it via Pydantic, and logs it as JSON with automatic
    timestamp and context injection.

    Args:
        event_type (AuditEventType): Type of audit event
        transfer_session_id (str): Unique correlation ID for end-to-end tracing
        sender_agency (str): Code of sending agency (e.g., 'dot', 'gsa')
        receiver_agency (str): Code of receiving agency
        stage (str): Pipeline stage (e.g., 'sender', 'transfer', 'receiver')
        outcome (EventOutcome): Result of operation (success, partial, failure).
                               Defaults to SUCCESS.
        destination_host (Optional[str]): For transfer events, SFTP server hostname
        bytes_transferred (Optional[int]): For transfer events, number of bytes transferred
        details (Optional[Dict[str, Any]]): Additional event context (extensible)

    Returns:
        AuditEvent: The validated event object that was logged

    Raises:
        ValueError: If any required field is invalid or missing
        pydantic.ValidationError: If event model validation fails

    Example:
        event = log_event(
            event_type=AuditEventType.COMPRESS,
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS,
            details={"compression_algorithm": "gzip", "compression_ratio": 0.45},
        )
    """
    # Create and validate event via Pydantic
    event = AuditEvent(
        event_type=event_type,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage=stage,
        outcome=outcome,
        destination_host=destination_host,
        bytes_transferred=bytes_transferred,
        details=details,
    )

    # Emit as structured JSON log entry
    # JsonFormatter will automatically inject transfer_session_id from context
    # and convert the event to structured log format
    log_entry = event.to_structured_log()
    _logger.info(
        prefix_log_message(
            f"{event_type.value}: {outcome.value}",
            transfer_session_id=transfer_session_id,
        ),
        extra={"event_data": log_entry},
    )

    return event


# ============================================================================
# Day 1 Event Emission Helpers
# ============================================================================


def log_pipeline_start(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log PIPELINE_START event.

    Emitted when sender initiates the transfer pipeline. This is always the
    first event in the transfer lifecycle and establishes the correlation ID.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        details: Optional context (e.g., agent_mode, environment)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.PIPELINE_START,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="sender",
        outcome=EventOutcome.SUCCESS,
        details=details,
    )


def log_extract_data(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log EXTRACT_DATA event.

    Emitted after data is extracted from source system. This event can capture
    file count, data size, or extraction errors.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of extraction (SUCCESS, PARTIAL, FAILURE)
        details: Optional context (e.g., file_count, total_bytes, error_reason)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.EXTRACT_DATA,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="sender",
        outcome=outcome,
        details=details,
    )


def log_policy_check(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log POLICY_CHECK event.

    Emitted after authorization and compliance checks. Failures here prevent
    transfer progression.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of policy check (SUCCESS, FAILURE)
        details: Optional context (e.g., policies_checked, denial_reason)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.POLICY_CHECK,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="sender",
        outcome=outcome,
        details=details,
    )


def log_compress(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log COMPRESS event.

    Emitted after extracted data is compressed for transfer. Captures
    compression algorithm and ratio.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of compression (SUCCESS, FAILURE)
        details: Optional context (e.g., algorithm, compression_ratio)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.COMPRESS,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="sender",
        outcome=outcome,
        details=details,
    )


def log_manifest_created(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log MANIFEST_CREATED event.

    Emitted after transfer manifest is created with metadata and checksums.
    This manifest is used by receiver for validation.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of manifest creation (SUCCESS, FAILURE)
        details: Optional context (e.g., checksum_algorithm, file_list)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.MANIFEST_CREATED,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="sender",
        outcome=outcome,
        details=details,
    )


def log_sftp_transfer_start(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    destination_host: str,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log SFTP_TRANSFER_START event.

    Emitted when SFTP transfer to partner agency begins.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        destination_host: Hostname of receiving SFTP server
        details: Optional context (e.g., port, username)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.SFTP_TRANSFER_START,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="transfer",
        outcome=EventOutcome.SUCCESS,
        destination_host=destination_host,
        details=details,
    )


def log_sftp_transfer_complete(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    destination_host: str,
    bytes_transferred: int,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log SFTP_TRANSFER_COMPLETE event.

    Emitted when SFTP transfer to partner agency completes (success or failure).

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        destination_host: Hostname of receiving SFTP server
        bytes_transferred: Number of bytes successfully transferred
        outcome: Result of transfer (SUCCESS, PARTIAL, FAILURE)
        details: Optional context (e.g., transfer_duration_seconds, error_reason)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="transfer",
        outcome=outcome,
        destination_host=destination_host,
        bytes_transferred=bytes_transferred,
        details=details,
    )


def log_validate_manifest(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log VALIDATE_MANIFEST event.

    Emitted when receiver validates received manifest integrity.
    Validates checksums and file count match expected values.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of validation (SUCCESS, FAILURE)
        details: Optional context (e.g., validation_errors)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.VALIDATE_MANIFEST,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="receiver",
        outcome=outcome,
        details=details,
    )


def log_decompress(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log DECOMPRESS event.

    Emitted when receiver decompresses received payload.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of decompression (SUCCESS, FAILURE)
        details: Optional context (e.g., decompressed_size, algorithm)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.DECOMPRESS,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="receiver",
        outcome=outcome,
        details=details,
    )


def log_store_data(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log STORE_DATA event.

    Emitted when receiver stores decompressed data in final location (S3).
    This is the last storage step before pipeline completion.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Result of storage (SUCCESS, FAILURE)
        details: Optional context (e.g., s3_bucket, storage_path)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.STORE_DATA,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="receiver",
        outcome=outcome,
        details=details,
    )


def log_pipeline_complete(
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
    outcome: EventOutcome = EventOutcome.SUCCESS,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    """
    Log PIPELINE_COMPLETE event.

    Emitted when entire pipeline execution completes (success or failure).
    This is always the final event in the transfer lifecycle.

    Args:
        transfer_session_id: Unique transfer correlation ID
        sender_agency: Sending agency code
        receiver_agency: Receiving agency code
        outcome: Overall pipeline result (SUCCESS, PARTIAL, FAILURE)
        details: Optional context (e.g., total_duration_seconds, summary)

    Returns:
        AuditEvent: The logged event
    """
    return log_event(
        event_type=AuditEventType.PIPELINE_COMPLETE,
        transfer_session_id=transfer_session_id,
        sender_agency=sender_agency,
        receiver_agency=receiver_agency,
        stage="receiver",
        outcome=outcome,
        details=details,
    )


__all__ = [
    "log_event",
    "log_pipeline_start",
    "log_extract_data",
    "log_policy_check",
    "log_compress",
    "log_manifest_created",
    "log_sftp_transfer_start",
    "log_sftp_transfer_complete",
    "log_validate_manifest",
    "log_decompress",
    "log_store_data",
    "log_pipeline_complete",
]
