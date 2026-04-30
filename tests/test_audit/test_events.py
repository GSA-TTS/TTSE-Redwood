"""
Unit tests for audit event models and event types.

This module tests:
- AuditEventType enumeration (11 Day 1 events)
- EventOutcome enumeration (SUCCESS, PARTIAL, FAILURE)
- AuditEvent model creation and validation
- Required and optional field validation
- JSON serialization to structured log format
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from redwood_dataagent.audit.events import (
    AuditEvent,
    AuditEventType,
    EventOutcome,
)


class TestAuditEventType:
    """Test suite for AuditEventType enumeration."""

    def test_all_day1_event_types_exist(self):
        """Test that all 11 Day 1 event types are defined."""
        expected_events = {
            AuditEventType.PIPELINE_START,
            AuditEventType.EXTRACT_DATA,
            AuditEventType.POLICY_CHECK,
            AuditEventType.COMPRESS,
            AuditEventType.MANIFEST_CREATED,
            AuditEventType.SFTP_TRANSFER_START,
            AuditEventType.SFTP_TRANSFER_COMPLETE,
            AuditEventType.VALIDATE_MANIFEST,
            AuditEventType.DECOMPRESS,
            AuditEventType.STORE_DATA,
            AuditEventType.PIPELINE_COMPLETE,
        }

        # Verify all expected events exist
        for event_type in expected_events:
            assert event_type is not None
            assert isinstance(event_type.value, str)

        # Verify there are exactly 11
        assert len(expected_events) == 11

    def test_event_type_string_values(self):
        """Test that event types map to lowercase snake_case strings."""
        assert AuditEventType.PIPELINE_START.value == "pipeline_start"
        assert AuditEventType.EXTRACT_DATA.value == "extract_data"
        assert AuditEventType.POLICY_CHECK.value == "policy_check"
        assert AuditEventType.COMPRESS.value == "compress"
        assert AuditEventType.MANIFEST_CREATED.value == "manifest_created"
        assert AuditEventType.SFTP_TRANSFER_START.value == "sftp_transfer_start"
        assert AuditEventType.SFTP_TRANSFER_COMPLETE.value == "sftp_transfer_complete"
        assert AuditEventType.VALIDATE_MANIFEST.value == "validate_manifest"
        assert AuditEventType.DECOMPRESS.value == "decompress"
        assert AuditEventType.STORE_DATA.value == "store_data"
        assert AuditEventType.PIPELINE_COMPLETE.value == "pipeline_complete"

    def test_event_type_is_string_enum(self):
        """Test that AuditEventType is a string enum."""
        assert issubclass(AuditEventType, str)
        assert AuditEventType.PIPELINE_START == "pipeline_start"


class TestEventOutcome:
    """Test suite for EventOutcome enumeration."""

    def test_event_outcomes_defined(self):
        """Test that all outcome types are defined."""
        outcomes = {EventOutcome.SUCCESS, EventOutcome.PARTIAL, EventOutcome.FAILURE}
        assert len(outcomes) == 3

    def test_outcome_string_values(self):
        """Test outcome string values."""
        assert EventOutcome.SUCCESS.value == "success"
        assert EventOutcome.PARTIAL.value == "partial"
        assert EventOutcome.FAILURE.value == "failure"

    def test_outcome_is_string_enum(self):
        """Test that EventOutcome is a string enum."""
        assert issubclass(EventOutcome, str)
        assert EventOutcome.SUCCESS == "success"


class TestAuditEvent:
    """Test suite for AuditEvent model."""

    def test_valid_event_creation(self):
        """Test creating a valid audit event with all required fields."""
        event = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS
        )

        assert event.event_type == AuditEventType.PIPELINE_START
        assert event.transfer_session_id == "transfer-20260317-001"
        assert event.sender_agency == "dot"
        assert event.receiver_agency == "gsa"
        assert event.stage == "sender"
        assert event.outcome == EventOutcome.SUCCESS
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_event_empty_transfer_session_id_rejected(self):
        """Test that empty transfer_session_id is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AuditEvent(
                event_type=AuditEventType.PIPELINE_START,
                transfer_session_id="",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="sender",
                outcome=EventOutcome.SUCCESS
            )

        assert "transfer_session_id" in str(exc_info.value).lower()

    def test_event_optional_transfer_details(self):
        """Test creating an event with optional transfer details."""
        event = AuditEvent(
            event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="transfer",
            outcome=EventOutcome.SUCCESS,
            destination_host="fde-gsa-dev-sftp.transfer.amazonaws.com",
            bytes_transferred=102400
        )

        assert event.destination_host == "fde-gsa-dev-sftp.transfer.amazonaws.com"
        assert event.bytes_transferred == 102400

    def test_event_negative_bytes_rejected(self):
        """Test that negative bytes_transferred is rejected."""
        with pytest.raises(ValidationError):
            AuditEvent(
                event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
                transfer_session_id="transfer-20260317-001",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="transfer",
                outcome=EventOutcome.SUCCESS,
                bytes_transferred=-1
            )

    def test_event_with_details_dict(self):
        """Test creating an event with optional details context."""
        details = {
            "file_count": 5,
            "total_size_bytes": 1024000,
            "compression_ratio": 0.75
        }

        event = AuditEvent(
            event_type=AuditEventType.COMPRESS,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS,
            details=details
        )

        assert event.details == details
        assert event.details["file_count"] == 5

    def test_event_timestamp_defaults_to_now(self):
        """Test that timestamp defaults to current UTC time."""
        before = datetime.now(timezone.utc)
        event = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS
        )
        after = datetime.now(timezone.utc)

        assert before <= event.timestamp <= after

    def test_event_to_structured_log(self):
        """Test conversion of event to structured log JSON format."""
        event = AuditEvent(
            event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="transfer",
            outcome=EventOutcome.SUCCESS,
            destination_host="fde-gsa-dev-sftp.transfer.amazonaws.com",
            bytes_transferred=102400,
            details={"files_transferred": 3}
        )

        log_dict = event.to_structured_log()

        # Verify all fields are in the output
        assert log_dict["event_type"] == "sftp_transfer_complete"
        assert log_dict["transfer_session_id"] == "transfer-20260317-001"
        assert log_dict["sender_agency"] == "dot"
        assert log_dict["receiver_agency"] == "gsa"
        assert log_dict["stage"] == "transfer"
        assert log_dict["outcome"] == "success"
        assert log_dict["destination_host"] == "fde-gsa-dev-sftp.transfer.amazonaws.com"
        assert log_dict["bytes_transferred"] == 102400
        assert log_dict["timestamp"].endswith("Z")

    def test_event_to_structured_log_excludes_none_values(self):
        """Test that None optional values are included as None in structured log."""
        event = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-20260317-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS
        )

        log_dict = event.to_structured_log()

        # Optional fields should be None or empty dict
        assert log_dict["destination_host"] is None
        assert log_dict["bytes_transferred"] is None
        assert log_dict["details"] == {}

    def test_all_event_types_can_be_created(self):
        """Test that all 11 event types can be instantiated."""
        event_types = [
            AuditEventType.PIPELINE_START,
            AuditEventType.EXTRACT_DATA,
            AuditEventType.POLICY_CHECK,
            AuditEventType.COMPRESS,
            AuditEventType.MANIFEST_CREATED,
            AuditEventType.SFTP_TRANSFER_START,
            AuditEventType.SFTP_TRANSFER_COMPLETE,
            AuditEventType.VALIDATE_MANIFEST,
            AuditEventType.DECOMPRESS,
            AuditEventType.STORE_DATA,
            AuditEventType.PIPELINE_COMPLETE,
        ]

        for event_type in event_types:
            event = AuditEvent(
                event_type=event_type,
                transfer_session_id="test-session",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="test",
                outcome=EventOutcome.SUCCESS
            )

            assert event is not None
            assert event.event_type == event_type

    def test_event_with_all_outcomes(self):
        """Test event creation with all outcome types."""
        for outcome in [EventOutcome.SUCCESS, EventOutcome.PARTIAL, EventOutcome.FAILURE]:
            event = AuditEvent(
                event_type=AuditEventType.EXTRACT_DATA,
                transfer_session_id="transfer-001",
                sender_agency="dot",
                receiver_agency="gsa",
                stage="sender",
                outcome=outcome
            )

            assert event.outcome == outcome

    def test_event_model_config_includes_example(self):
        """Test that model is configured with JSON schema example."""
        config = AuditEvent.model_config
        assert "json_schema_extra" in config
        example = config["json_schema_extra"]["example"]
        assert example["event_type"] == "pipeline_start"
        assert example["transfer_session_id"] == "transfer-20260317-001"

    def test_event_sender_receiver_agency_optional(self):
        """sender_agency and receiver_agency can be empty — pods only know their own agency."""
        # Sender pod: knows sender_agency, not receiver_agency
        event = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="",
            stage="sender",
            outcome=EventOutcome.SUCCESS
        )
        assert event.sender_agency == "dot"
        assert event.receiver_agency == ""

        # Receiver pod: knows receiver_agency, not sender_agency
        event2 = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-001",
            sender_agency="",
            receiver_agency="gsa",
            stage="receiver",
            outcome=EventOutcome.SUCCESS
        )
        assert event2.sender_agency == ""
        assert event2.receiver_agency == "gsa"

    def test_event_timestamp_iso_format_with_z_suffix(self):
        """Test that timestamp in structured log is ISO 8601 with Z suffix."""
        event = AuditEvent(
            event_type=AuditEventType.PIPELINE_START,
            transfer_session_id="transfer-001",
            sender_agency="dot",
            receiver_agency="gsa",
            stage="sender",
            outcome=EventOutcome.SUCCESS
        )

        log_dict = event.to_structured_log()
        timestamp = log_dict["timestamp"]

        # ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ or with microseconds
        assert timestamp.endswith("Z")
        assert "T" in timestamp
        assert timestamp.count("-") >= 2  # At least YYYY-MM-DD
        assert timestamp.count(":") >= 2  # At least HH:MM:SS
