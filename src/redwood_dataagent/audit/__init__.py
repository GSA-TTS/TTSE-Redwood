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
    from redwood_dataagent.audit.events import AuditEvent, AuditEventType, EventOutcome
    
    event = AuditEvent(
        event_type=AuditEventType.PIPELINE_START,
        transfer_session_id="transfer-001",
        sender_agency="dot",
        receiver_agency="gsa",
        stage="sender",
        outcome=EventOutcome.SUCCESS
    )
    log_entry = event.to_structured_log()
"""

from redwood_dataagent.audit.events import (
    AuditEvent,
    AuditEventType,
    EventOutcome,
)

__all__ = [
    "AuditEvent",
    "AuditEventType",
    "EventOutcome",
]
