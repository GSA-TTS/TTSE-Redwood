"""Tests for logging infrastructure and context variable tracking."""

from __future__ import annotations

import json
import logging

import pytest

from redwood_dataagent.logging_utils import (
    JsonFormatter,
    _agent_mode,
    _transfer_session_id,
    configure_logging,
    get_agent_mode,
    get_logger,
    get_transfer_session_id,
    logging_context,
    prefix_log_message,
    set_agent_mode,
    set_transfer_session_id,
)


@pytest.fixture(autouse=True)
def reset_context():
    """Reset context variable before each test for isolation."""
    yield
    # After each test, reset the context variable to None for test isolation
    # This prevents test cross-contamination via shared contextvars state
    _agent_mode.set(None)
    _transfer_session_id.set(None)


class TestJsonFormatter:
    """JsonFormatter tests."""

    def test_format_basic_record(self):
        """Basic log record includes level, logger, and message."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        assert payload["level"] == "INFO"
        assert payload["logger"] == "test_logger"
        assert payload["message"] == "test message"

    def test_format_includes_transfer_session_id_from_context(self):
        """transfer_session_id from context is included in output."""
        # Set session ID in context
        set_transfer_session_id("session-123")

        # Create a log record without explicitly passing session ID
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test with session",
            args=(),
            exc_info=None,
        )
        # Format should automatically pull session from context
        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        # This verifies session ID is auto-injected from context
        assert payload["transfer_session_id"] == "session-123"

    def test_format_includes_agent_mode_from_context(self):
        """agent_mode from context is included in output."""
        set_agent_mode("receiver")

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test with mode",
            args=(),
            exc_info=None,
        )

        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        assert payload["agent_mode"] == "receiver"

    def test_format_excludes_session_id_when_not_set(self):
        """transfer_session_id is excluded from output when not set."""
        # Reset to ensure not set
        _transfer_session_id.set(None)

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test without session",
            args=(),
            exc_info=None,
        )
        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        # Should not include transfer_session_id key if not set
        assert "transfer_session_id" not in payload or payload["transfer_session_id"] is None

    def test_format_includes_custom_event(self):
        """Custom event field is included in output."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.event = "TRANSFER_START"

        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        assert payload["event"] == "TRANSFER_START"

    def test_format_includes_extra_fields(self):
        """Extra fields are included in output."""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.extra = {"custom_field": "custom_value", "count": 42}

        formatter = JsonFormatter()
        formatted = formatter.format(record)
        payload = json.loads(formatted)

        assert payload["custom_field"] == "custom_value"
        assert payload["count"] == 42

    def test_format_json_is_valid(self):
        """Formatted output is valid JSON."""
        set_transfer_session_id("json-test-session")

        record = logging.LogRecord(
            name="test_logger",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="test json validity",
            args=(),
            exc_info=None,
        )
        record.event = "TEST_EVENT"

        formatter = JsonFormatter()
        formatted = formatter.format(record)

        # Should not raise JSONDecodeError
        payload = json.loads(formatted)
        assert isinstance(payload, dict)
        assert all(isinstance(k, str) for k in payload.keys())


class TestTransferSessionIdContext:
    """Transfer session ID context tracking tests."""

    def test_set_and_get_transfer_session_id(self):
        """set_transfer_session_id stores value in context."""
        set_transfer_session_id("session-abc")
        assert get_transfer_session_id() == "session-abc"

    def test_set_and_get_agent_mode(self):
        """set_agent_mode stores value in context."""
        set_agent_mode("sender")
        assert get_agent_mode() == "sender"

    def test_set_multiple_session_ids_overwrites(self):
        """Setting session ID multiple times overwrites previous value."""
        set_transfer_session_id("session-1")
        assert get_transfer_session_id() == "session-1"

        set_transfer_session_id("session-2")
        assert get_transfer_session_id() == "session-2"

    def test_transfer_session_id_with_uuid_format(self):
        """transfer_session_id works with UUID format."""
        import uuid

        session_id = str(uuid.uuid4())
        set_transfer_session_id(session_id)
        assert get_transfer_session_id() == session_id


class TestLoggingContext:
    """logging_context context manager tests."""

    def test_logging_context_temporarily_overrides_session_id(self):
        """logging_context temporarily overrides transfer_session_id."""
        set_transfer_session_id("original-session")

        # Use context manager to temporarily change session ID
        with logging_context("temp-session"):
            # Inside context, the override is active
            assert get_transfer_session_id() == "temp-session"

        # Outside context, session reverts to original value
        assert get_transfer_session_id() == "original-session"

    def test_logging_context_restores_on_exception(self):
        """logging_context restores session ID even if exception occurs."""
        set_transfer_session_id("original-session")

        # Verify exception handling still restores context (important for robustness)
        with pytest.raises(ValueError):
            with logging_context("temp-session"):
                assert get_transfer_session_id() == "temp-session"
                raise ValueError("test error")

        # Session must be restored even though exception occurred
        assert get_transfer_session_id() == "original-session"

    def test_logging_context_nested_multiple_levels(self):
        """Nested logging_context blocks work correctly."""
        set_transfer_session_id("level-0")

        # Test deep nesting - each level should see its own override
        # and restore properly on exit
        with logging_context("level-1"):
            assert get_transfer_session_id() == "level-1"

            with logging_context("level-2"):
                assert get_transfer_session_id() == "level-2"

                with logging_context("level-3"):
                    assert get_transfer_session_id() == "level-3"

                # Exiting level-3 context restores level-2
                assert get_transfer_session_id() == "level-2"

            # Exiting level-2 context restores level-1
            assert get_transfer_session_id() == "level-1"

        # Exiting level-1 context restores level-0
        assert get_transfer_session_id() == "level-0"

    def test_logging_context_empty_nesting(self):
        """logging_context works with empty initial value."""
        # Ensure context starts empty
        _transfer_session_id.set(None)

        with logging_context("temp-session"):
            assert get_transfer_session_id() == "temp-session"

        # Should be back to None or unset
        assert get_transfer_session_id() is None


class TestPrefixLogMessage:
    """prefix_log_message helper tests."""

    def test_prefix_log_message_uses_context(self):
        """Prefix helper uses current context when explicit values are absent."""
        set_agent_mode("receiver")
        set_transfer_session_id("session-123")

        assert prefix_log_message("Processing transfer") == "[receiver][session-123] Processing transfer"

    def test_prefix_log_message_accepts_explicit_values(self):
        """Prefix helper supports explicit values without relying on context."""
        assert (
            prefix_log_message(
                "Executing agent workflow",
                agent_mode="sender",
                transfer_session_id="session-456",
            )
            == "[sender][session-456] Executing agent workflow"
        )


class TestGetLogger:
    """get_logger function tests."""

    def test_get_logger_returns_logger_instance(self):
        """get_logger returns a logging.Logger instance."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_logger_with_different_names(self):
        """get_logger creates loggers with different names."""
        logger1 = get_logger("module_a")
        logger2 = get_logger("module_b")

        assert logger1.name == "module_a"
        assert logger2.name == "module_b"

    def test_get_logger_returns_same_instance_for_same_name(self):
        """get_logger returns the same instance for the same name."""
        logger1 = get_logger("same_module")
        logger2 = get_logger("same_module")

        assert logger1 is logger2

    def test_get_logger_respects_hierarchy(self):
        """get_logger respects logger hierarchy."""
        parent_logger = get_logger("parent")
        child_logger = get_logger("parent.child")

        # Child logger should have parent in its hierarchy
        assert child_logger.parent is parent_logger


class TestConfigureLogging:
    """configure_logging function tests."""

    def test_configure_logging_sets_formatter(self):
        """configure_logging applies JsonFormatter to root logger."""
        configure_logging("DEBUG")

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_configure_logging_sets_level(self):
        """configure_logging sets the specified log level."""
        configure_logging("WARNING")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

    def test_configure_logging_accepts_all_levels(self):
        """configure_logging accepts standard log level names."""
        for level_name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            configure_logging(level_name)
            root_logger = logging.getLogger()
            assert root_logger.level == getattr(logging, level_name)

    def test_configure_logging_suppresses_paramiko_chatter(self):
        """Paramiko transport/session chatter is clamped at WARNING+."""
        configure_logging("INFO")

        assert logging.getLogger("paramiko").level == logging.WARNING
        assert logging.getLogger("paramiko.transport").level == logging.WARNING


class TestIntegration:
    """Integration tests for full logging pipeline."""

    def test_full_logging_pipeline_with_session_id(self, caplog):
        """Full pipeline: configure → set session → log → verify output."""
        # STEP 1: Configure JSON logging
        configure_logging("INFO")
        # STEP 2: Set the session ID that will be injected into all logs
        set_transfer_session_id("integration-test-session")

        logger = get_logger("integration_test")

        with caplog.at_level(logging.INFO):
            record = logging.LogRecord(
                name="integration_test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="integration test message",
                args=(),
                exc_info=None,
            )
            record.event = "TEST_EVENT"
            record.extra = {"data": "test_data"}
            # STEP 3: Format the record - session ID should be auto-injected
            formatter = JsonFormatter()
            formatted = formatter.format(record)
            payload = json.loads(formatted)

        # STEP 4: Verify all fields are present in the JSON output
        assert payload["transfer_session_id"] == "integration-test-session"
        assert payload["event"] == "TEST_EVENT"
        assert payload["data"] == "test_data"
        assert payload["message"] == "integration test message"

    def test_logging_context_with_actual_logger(self, caplog):
        """Verify logging_context affects actual logger output."""
        # Reset to clean state for this integration test
        _transfer_session_id.set(None)
        configure_logging("INFO")
        # Establish main session ID
        set_transfer_session_id("session-main")

        logger = get_logger("context_test")

        # SCENARIO 1: Log with main session
        record1 = logging.LogRecord(
            name="context_test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="main session message",
            args=(),
            exc_info=None,
        )
        main_payload = json.loads(JsonFormatter().format(record1))
        assert main_payload["transfer_session_id"] == "session-main"

        # SCENARIO 2: Temporarily override session within logging_context
        with logging_context("session-override"):
            record2 = logging.LogRecord(
                name="context_test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="override session message",
                args=(),
                exc_info=None,
            )
            override_payload = json.loads(JsonFormatter().format(record2))
            assert override_payload["transfer_session_id"] == "session-override"

        # SCENARIO 3: Verify session reverted to main after context exit
        record3 = logging.LogRecord(
            name="context_test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="back to main session",
            args=(),
            exc_info=None,
        )
        back_payload = json.loads(JsonFormatter().format(record3))
        assert back_payload["transfer_session_id"] == "session-main"

    def test_logging_context_with_exception_handling(self):
        """Verify logging_context properly restores state on exception."""
        set_transfer_session_id("original")

        class CustomException(Exception):  # noqa: N818
            pass

        try:
            with logging_context("temporary"):
                assert get_transfer_session_id() == "temporary"
                raise CustomException("Test error")
        except CustomException:
            pass

        assert get_transfer_session_id() == "original"
