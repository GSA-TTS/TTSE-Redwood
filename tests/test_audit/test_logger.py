"""
Unit tests for audit event logger.

This module tests:
- Core log_event() function with all required/optional parameters
- All 11 convenience helper functions for Day 1 events
- Event type, stage, and outcome correctness
- Optional fields (destination_host, bytes_transferred, details)
- Validation and error handling
- Consistency with Pydantic AuditEvent model
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
from redwood_dataagent.logging_utils import set_agent_mode


class TestCoreLogEvent:
    """Tests for the core log_event() function."""

    def test_log_event_with_required_fields(self):
        """Test logging event with only required fields."""
        event = log_event(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
        )

        assert event.event_type == AuditEventType.PIPELINE_START
        assert event.transfer_session_id == "transfer-001"
        assert event.sender_agency == "dot"
        assert event.receiver_agency == "gsa"
        assert event.stage == "sender"
        assert event.outcome == EventOutcome.SUCCESS  # Default
        assert event.destination_host is None
        assert event.bytes_transferred is None
        assert event.details is None

    def test_log_event_with_all_fields(self):
        """Test logging event with all optional fields populated."""
        details = {"file_count": 42, "checksum_algorithm": "sha256"}
        event = log_event(
            event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="transfer",
            outcome=EventOutcome.SUCCESS,
            destination_host="sftp.example.com",
            bytes_transferred=1_048_576,
            details=details,
        )

        assert event.event_type == AuditEventType.SFTP_TRANSFER_COMPLETE
        assert event.outcome == EventOutcome.SUCCESS
        assert event.destination_host == "sftp.example.com"
        assert event.bytes_transferred == 1_048_576
        assert event.details == details

    def test_log_event_with_failure_outcome(self):
        """Test logging failure event with error details."""
        error_details = {"error_reason": "Connection refused", "retry_count": 3}
        event = log_event(
            event_type=AuditEventType.EXTRACT_DATA,
            transfer_session_id="transfer-003",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.FAILURE,
            details=error_details,
        )

        assert event.outcome == EventOutcome.FAILURE
        assert event.details["error_reason"] == "Connection refused"

    def test_log_event_with_partial_outcome(self):
        """Test logging partial success event."""
        details = {"processed": 85, "failed": 15, "total": 100}
        event = log_event(
            event_type=AuditEventType.EXTRACT_DATA,
            transfer_session_id="transfer-004",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.PARTIAL,
            details=details,
        )

        assert event.outcome == EventOutcome.PARTIAL

    def test_log_event_returns_audit_event(self):
        """Test that log_event returns AuditEvent instance."""
        event = log_event(
            event_type=AuditEventType.POLICY_CHECK,
            transfer_session_id="transfer-005",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
        )

        assert isinstance(event, AuditEvent)

    def test_log_event_timestamp_is_utc(self):
        """Test that event timestamp is in UTC."""
        before = datetime.now(timezone.utc)
        event = log_event(
            event_type=AuditEventType.COMPRESS,
            transfer_session_id="transfer-006",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
        )
        after = datetime.now(timezone.utc)

        assert before <= event.timestamp <= after
        assert event.timestamp.tzinfo == timezone.utc

    def test_log_event_validates_empty_transfer_session_id(self):
        """Test that empty transfer_session_id raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            log_event(
                event_type=AuditEventType.MANIFEST_CREATED,
                transfer_session_id="",  # Invalid: empty string
                sender_agency="dot",
                receiver_agency="gsa",
                stage="sender",
            )

    def test_log_event_validates_negative_bytes_transferred(self):
        """Test that negative bytes_transferred raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            log_event(
                event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
                transfer_session_id="transfer-007",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="transfer",
                bytes_transferred=-1,  # Invalid: negative
                destination_host="sftp.example.com",
            )

    def test_log_event_prefixes_message_with_agent_mode_and_transfer_id(self):
        """Readable audit message includes agent mode and transfer ID context."""
        set_agent_mode("receiver")

        with patch("redwood_dataagent.audit.logger._logger") as mock_logger:
            log_event(
                event_type=AuditEventType.PIPELINE_START,
                transfer_session_id="transfer-001",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="sender",
            )

        mock_logger.info.assert_called_once()
        assert mock_logger.info.call_args.args[0] == "[receiver][transfer-001] pipeline_start: success"
        set_agent_mode(None)


class TestPipelineStartHelper:
    """Tests for log_pipeline_start() convenience function."""

    def test_pipeline_start_basic(self):
        """Test basic pipeline start event."""
        event = log_pipeline_start(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert event.event_type == AuditEventType.PIPELINE_START
        assert event.stage == "sender"
        assert event.outcome == EventOutcome.SUCCESS

    def test_pipeline_start_with_details(self):
        """Test pipeline start with optional details."""
        details = {"agent_mode": "sender", "environment": "dev"}
        event = log_pipeline_start(
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            details=details,
        )

        assert event.details == details


class TestExtractDataHelper:
    """Tests for log_extract_data() convenience function."""

    def test_extract_data_success(self):
        """Test successful data extraction event."""
        event = log_extract_data(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
        )

        assert event.event_type == AuditEventType.EXTRACT_DATA
        assert event.stage == "sender"
        assert event.outcome == EventOutcome.SUCCESS

    def test_extract_data_with_details(self):
        """Test data extraction with file count and size."""
        details = {"file_count": 42, "total_bytes": 10_485_760}
        event = log_extract_data(
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details=details,
        )

        assert event.details["file_count"] == 42


class TestPolicyCheckHelper:
    """Tests for log_policy_check() convenience function."""

    def test_policy_check_pass(self):
        """Test successful policy check."""
        event = log_policy_check(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
        )

        assert event.event_type == AuditEventType.POLICY_CHECK
        assert event.stage == "sender"

    def test_policy_check_fail(self):
        """Test failed policy check."""
        details = {"denial_reason": "Agency not authorized"}
        event = log_policy_check(
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.FAILURE,
            details=details,
        )

        assert event.outcome == EventOutcome.FAILURE


class TestCompressHelper:
    """Tests for log_compress() convenience function."""

    def test_compress_success(self):
        """Test successful compression."""
        details = {"algorithm": "gzip", "compression_ratio": 0.45}
        event = log_compress(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details=details,
        )

        assert event.event_type == AuditEventType.COMPRESS
        assert event.stage == "sender"


class TestManifestCreatedHelper:
    """Tests for log_manifest_created() convenience function."""

    def test_manifest_created(self):
        """Test manifest creation event."""
        details = {"checksum_algorithm": "sha256", "file_list": ["file1.txt"]}
        event = log_manifest_created(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details=details,
        )

        assert event.event_type == AuditEventType.MANIFEST_CREATED
        assert event.stage == "sender"


class TestSFTPTransferHelpers:
    """Tests for SFTP transfer event helpers."""

    def test_sftp_transfer_start(self):
        """Test SFTP transfer start event."""
        event = log_sftp_transfer_start(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            destination_host="sftp.receiving-agency.gov",
        )

        assert event.event_type == AuditEventType.SFTP_TRANSFER_START
        assert event.stage == "transfer"
        assert event.destination_host == "sftp.receiving-agency.gov"

    def test_sftp_transfer_complete_success(self):
        """Test successful SFTP transfer completion."""
        event = log_sftp_transfer_complete(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            destination_host="sftp.receiving-agency.gov",
            bytes_transferred=1_048_576,
            outcome=EventOutcome.SUCCESS,
        )

        assert event.event_type == AuditEventType.SFTP_TRANSFER_COMPLETE
        assert event.stage == "transfer"
        assert event.bytes_transferred == 1_048_576
        assert event.outcome == EventOutcome.SUCCESS

    def test_sftp_transfer_complete_partial(self):
        """Test partial SFTP transfer completion."""
        details = {"retry_count": 2, "timeout_errors": 1}
        event = log_sftp_transfer_complete(
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            destination_host="sftp.receiving-agency.gov",
            bytes_transferred=524_288,
            outcome=EventOutcome.PARTIAL,
            details=details,
        )

        assert event.outcome == EventOutcome.PARTIAL


class TestReceiverStageEvents:
    """Tests for receiver-stage event helpers."""

    def test_validate_manifest(self):
        """Test manifest validation event."""
        event = log_validate_manifest(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
        )

        assert event.event_type == AuditEventType.VALIDATE_MANIFEST
        assert event.stage == "receiver"

    def test_decompress(self):
        """Test data decompression event."""
        details = {"algorithm": "gzip", "decompressed_size": 2_097_152}
        event = log_decompress(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details=details,
        )

        assert event.event_type == AuditEventType.DECOMPRESS
        assert event.stage == "receiver"

    def test_store_data(self):
        """Test data storage event."""
        details = {"s3_bucket": "data-warehouse", "storage_path": "/outgoing/2026-03-24/"}
        event = log_store_data(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details=details,
        )

        assert event.event_type == AuditEventType.STORE_DATA
        assert event.stage == "receiver"


class TestPipelineCompleteHelper:
    """Tests for log_pipeline_complete() convenience function."""

    def test_pipeline_complete_success(self):
        """Test successful pipeline completion."""
        event = log_pipeline_complete(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
        )

        assert event.event_type == AuditEventType.PIPELINE_COMPLETE
        assert event.stage == "receiver"
        assert event.outcome == EventOutcome.SUCCESS

    def test_pipeline_complete_failure(self):
        """Test pipeline failure completion."""
        details = {"failure_stage": "SFTP_TRANSFER_COMPLETE", "error": "Connection timeout"}
        event = log_pipeline_complete(
            transfer_session_id="transfer-002",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.FAILURE,
            details=details,
        )

        assert event.outcome == EventOutcome.FAILURE
        assert event.details["failure_stage"] == "SFTP_TRANSFER_COMPLETE"

    def test_pipeline_complete_partial(self):
        """Test partial pipeline completion."""
        event = log_pipeline_complete(
            transfer_session_id="transfer-003",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.PARTIAL,
        )

        assert event.outcome == EventOutcome.PARTIAL


class TestEventConsistency:
    """Integration tests for event consistency across helpers."""

    def test_all_events_have_transfer_session_id(self):
        """Verify all events include transfer_session_id for correlation."""
        session_id = "transfer-integration-001"

        events = [
            log_pipeline_start(session_id, "dot", "gsa"),
            log_extract_data(session_id, "dot", "gsa"),
            log_policy_check(session_id, "dot", "gsa"),
            log_compress(session_id, "dot", "gsa"),
            log_manifest_created(session_id, "dot", "gsa"),
            log_sftp_transfer_start(session_id, "dot", "gsa", "sftp.example.com"),
            log_sftp_transfer_complete(session_id, "dot", "gsa", "sftp.example.com", 1_000_000),
            log_validate_manifest(session_id, "dot", "gsa"),
            log_decompress(session_id, "dot", "gsa"),
            log_store_data(session_id, "dot", "gsa"),
            log_pipeline_complete(session_id, "dot", "gsa"),
        ]

        for event in events:
            assert event.transfer_session_id == session_id

    def test_all_events_have_consistent_agencies(self):
        """Verify all events maintain sender/receiver agency consistency."""
        sender = "dot"
        receiver = "gsa"

        events = [
            log_pipeline_start("id-1", sender, receiver),
            log_extract_data("id-2", sender, receiver),
            log_policy_check("id-3", sender, receiver),
        ]

        for event in events:
            assert event.sender_agency == sender
            assert event.receiver_agency == receiver

    def test_stage_progression(self):
        """Test correct stage progression through pipeline."""
        sender_events = [
            log_pipeline_start("id-1", "dot", "gsa"),
            log_extract_data("id-1", "dot", "gsa"),
            log_policy_check("id-1", "dot", "gsa"),
            log_compress("id-1", "dot", "gsa"),
            log_manifest_created("id-1", "dot", "gsa"),
        ]
        for event in sender_events:
            assert event.stage == "sender"

        transfer_events = [
            log_sftp_transfer_start("id-1", "dot", "gsa", "sftp.example.com"),
            log_sftp_transfer_complete("id-1", "dot", "gsa", "sftp.example.com", 1_000_000),
        ]
        for event in transfer_events:
            assert event.stage == "transfer"

        receiver_events = [
            log_validate_manifest("id-1", "dot", "gsa"),
            log_decompress("id-1", "dot", "gsa"),
            log_store_data("id-1", "dot", "gsa"),
            log_pipeline_complete("id-1", "dot", "gsa"),
        ]
        for event in receiver_events:
            assert event.stage == "receiver"


class TestEventSerialization:
    """Tests for event serialization to structured log format."""

    def test_event_to_structured_log(self):
        """Test conversion to structured logging format."""
        event = log_extract_data(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details={"file_count": 10},
        )

        log_entry = event.to_structured_log()

        # Verify all fields are present in structured log
        assert log_entry["event_type"] == "extract_data"
        assert log_entry["transfer_session_id"] == "transfer-001"
        assert log_entry["sender_agency"] == "dot"
        assert log_entry["outcome"] == "success"
        assert "timestamp" in log_entry

    def test_structured_log_json_serializable(self):
        """Test that structured log can be JSON serialized."""
        import json

        event = log_pipeline_complete(
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            outcome=EventOutcome.SUCCESS,
            details={"duration_seconds": 42.5},
        )

        log_entry = event.to_structured_log()
        json_str = json.dumps(log_entry)  # Should not raise

        assert json_str is not None
        assert "transfer-001" in json_str
