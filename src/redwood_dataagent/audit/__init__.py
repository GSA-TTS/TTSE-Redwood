"""
Audit module for TTSE Redwood Data Agent.

This module provides structured audit event definitions and logging capabilities
for end-to-end transfer tracking and compliance.

Day 1 events (see audit/events.py):
- PIPELINE_START, EXTRACT_DATA, POLICY_CHECK, COMPRESS, MANIFEST_CREATED
- SFTP_TRANSFER_START, SFTP_TRANSFER_COMPLETE
- VALIDATE_MANIFEST, DECOMPRESS, STORE_DATA, PIPELINE_COMPLETE

Outcomes: SUCCESS, PARTIAL, FAILURE

Example usage:
    from redwood_dataagent.audit import (
        AuditEventType,
        EventOutcome,
        log_pipeline_start,
        log_extract_data,
        log_pipeline_complete,
    )
    
    # Emit audit events for pipeline execution
    log_pipeline_start(
        transfer_session_id="transfer-001",
        sender_agency="dot",
        receiver_agency="gsa",
    )
    
    log_extract_data(
        transfer_session_id="transfer-001",
        sender_agency="dot",
        receiver_agency="gsa",
        outcome=EventOutcome.SUCCESS,
        details={"file_count": 42},
    )
    
    log_pipeline_complete(
        transfer_session_id="transfer-001",
        sender_agency="dot",
        receiver_agency="gsa",
        outcome=EventOutcome.SUCCESS,
    )
"""

from redwood_dataagent.audit.events import (
    AuditEvent,
    AuditEventType,
    EventOutcome,
)
from redwood_dataagent.audit.logger import (
    log_event,
    log_pipeline_start,
    log_extract_data,
    log_policy_check,
    log_compress,
    log_manifest_created,
    log_sftp_transfer_start,
    log_sftp_transfer_complete,
    log_validate_manifest,
    log_decompress,
    log_store_data,
    log_pipeline_complete,
)

__all__ = [
    # Event models and types
    "AuditEvent",
    "AuditEventType",
    "EventOutcome",
    # Logger functions
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
