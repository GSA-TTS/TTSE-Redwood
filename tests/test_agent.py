"""Unit tests for the agent runtime entrypoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from redwood_dataagent.agent import (
    _compute_checksum,
    _create_receiver_workflow,
    _create_sender_workflow,
    run_agent,
)
from redwood_dataagent.config import AgentConfig
from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.models.manifest import ChecksumAlgorithm


class TestComputeChecksum:
    """Tests for _compute_checksum()."""

    def test_compute_checksum_sha256_default(self, tmp_path: Path) -> None:
        """Compute checksum uses SHA256 by default."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        checksum = _compute_checksum(test_file)
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA256 hex digest is 64 characters

    def test_compute_checksum_consistent(self, tmp_path: Path) -> None:
        """Compute checksum returns same value for same file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        checksum1 = _compute_checksum(test_file)
        checksum2 = _compute_checksum(test_file)
        assert checksum1 == checksum2

    def test_compute_checksum_different_content(self, tmp_path: Path) -> None:
        """Compute checksum differs for different content."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        checksum1 = _compute_checksum(file1)
        checksum2 = _compute_checksum(file2)
        assert checksum1 != checksum2

    def test_compute_checksum_unsupported_algorithm_raises(self, tmp_path: Path) -> None:
        """Compute checksum raises error for unsupported algorithm."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Create a mock algorithm that's not SHA256
        class MockAlgorithm:
            pass

        with pytest.raises(StorageError, match="Unsupported checksum algorithm"):
            _compute_checksum(test_file, MockAlgorithm())  # type: ignore

    def test_compute_checksum_missing_file_raises(self, tmp_path: Path) -> None:
        """Compute checksum raises error for missing file."""
        missing_file = tmp_path / "missing.txt"

        with pytest.raises(StorageError, match="Failed to read file"):
            _compute_checksum(missing_file)


class TestSenderWorkflow:
    """Tests for _create_sender_workflow()."""

    def _make_config(self, **kwargs: object) -> AgentConfig:
        """Create a test AgentConfig with defaults."""
        defaults = {
            "agent_mode": "sender",
            "tenant": "tts",
            "environment": "development",
            "aws_region": "us-east-1",
            "log_level": "INFO",
            "transfer_session_id": "session-123",
            "sender_agency": "dot",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "dot-data-development-staging",
            "receiver_landing_bucket": "gsa-data-development-landing",
            "receiver_target_bucket": "gsa-data-development-target",
            "sender_data_file": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_sender_workflow_success(self, tmp_path: Path) -> None:
        """Sender workflow completes successfully."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(sender_data_file=str(source_file))
        exit_code = _create_sender_workflow(config)
        assert exit_code == 0

    def test_sender_workflow_requires_sender_file(self) -> None:
        """Sender workflow fails when no sender data file is configured for Day 1."""
        config = self._make_config()

        exit_code = _create_sender_workflow(config)

        assert exit_code == 1

    def test_sender_workflow_with_mock_policy(self, tmp_path: Path) -> None:
        """Sender workflow works with mocked policy approver."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(sender_data_file=str(source_file))

        with patch("redwood_dataagent.agent.PolicyApprover") as mock_approver_class:
            mock_approver = MagicMock()
            mock_approver.approve_transfer.return_value = True
            mock_approver_class.return_value = mock_approver

            exit_code = _create_sender_workflow(config)
            assert exit_code == 0
            mock_approver.approve_transfer.assert_called_once()

    def test_sender_workflow_uses_sender_provided_data_file(self, tmp_path: Path) -> None:
        """Sender workflow stages a sender-provided source file when configured."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(sender_data_file=str(source_file))

        exit_code = _create_sender_workflow(config)

        assert exit_code == 0

    def test_sender_workflow_policy_denied(self, tmp_path: Path) -> None:
        """Sender workflow exits with error when policy denies transfer."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(sender_data_file=str(source_file))

        with patch("redwood_dataagent.agent.PolicyApprover") as mock_approver_class:
            mock_approver = MagicMock()
            mock_approver.approve_transfer.return_value = False
            mock_approver_class.return_value = mock_approver

            exit_code = _create_sender_workflow(config)
            assert exit_code == 1

    def test_sender_workflow_handles_exception(self) -> None:
        """Sender workflow handles exceptions gracefully."""
        config = self._make_config()

        with patch("redwood_dataagent.agent._extract_data") as mock_extract:
            mock_extract.side_effect = RuntimeError("Test error")
            exit_code = _create_sender_workflow(config)
            assert exit_code == 1

    def test_sender_workflow_logs_events(self, tmp_path: Path) -> None:
        """Sender workflow logs audit events."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(sender_data_file=str(source_file))

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            with patch("redwood_dataagent.agent.log_pipeline_complete"):
                _create_sender_workflow(config)
                mock_start.assert_called_once()


class TestReceiverWorkflow:
    """Tests for _create_receiver_workflow()."""

    def _make_config(self, **kwargs: object) -> AgentConfig:
        """Create a test AgentConfig with defaults."""
        defaults = {
            "agent_mode": "receiver",
            "tenant": "tts",
            "environment": "development",
            "aws_region": "us-east-1",
            "log_level": "INFO",
            "transfer_session_id": "session-456",
            "sender_agency": "dot",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "dot-data-development-staging",
            "receiver_landing_bucket": "gsa-data-development-landing",
            "receiver_target_bucket": "gsa-data-development-target",
            "sender_data_file": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_receiver_workflow_success(self) -> None:
        """Receiver workflow completes successfully."""
        config = self._make_config()
        exit_code = _create_receiver_workflow(config)
        assert exit_code == 0

    def test_receiver_workflow_logs_events(self) -> None:
        """Receiver workflow logs audit events."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            with patch("redwood_dataagent.agent.log_pipeline_complete"):
                _create_receiver_workflow(config)
                mock_start.assert_called_once()

    def test_receiver_workflow_logs_manifest_validation_placeholder(self) -> None:
        """Receiver workflow logs manifest validation against landing storage."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_validate_manifest") as mock_validate:
            _create_receiver_workflow(config)
            assert mock_validate.call_count >= 1

    def test_receiver_workflow_logs_store_placeholder(self) -> None:
        """Receiver workflow logs store step against target storage."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_store_data") as mock_store:
            _create_receiver_workflow(config)
            mock_store.assert_called_once()

    def test_receiver_workflow_handles_exception(self) -> None:
        """Receiver workflow handles exceptions gracefully."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            mock_start.side_effect = RuntimeError("Test error")
            exit_code = _create_receiver_workflow(config)
            assert exit_code == 1


class TestRunAgent:
    """Tests for run_agent() entrypoint."""

    def _make_config(self, mode: str = "sender", **kwargs: object) -> AgentConfig:
        """Create a test AgentConfig with defaults."""
        defaults = {
            "agent_mode": mode,
            "tenant": "tts",
            "environment": "development",
            "aws_region": "us-east-1",
            "log_level": "INFO",
            "transfer_session_id": "session-123",
            "sender_agency": "dot",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "dot-data-development-staging",
            "receiver_landing_bucket": "gsa-data-development-landing",
            "receiver_target_bucket": "gsa-data-development-target",
            "sender_data_file": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_run_agent_sender_returns_success(self, tmp_path: Path) -> None:
        """Verify sender mode agent completes with exit code 0."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(mode="sender", sender_data_file=str(source_file))
        assert run_agent(config) == 0

    def test_run_agent_receiver_returns_success(self) -> None:
        """Verify receiver mode agent completes with exit code 0."""
        config = self._make_config(mode="receiver")
        assert run_agent(config) == 0

    def test_run_agent_sender_calls_sender_workflow(self) -> None:
        """run_agent routes sender mode to sender workflow."""
        config = self._make_config(mode="sender")

        with patch("redwood_dataagent.agent._create_sender_workflow") as mock_sender:
            mock_sender.return_value = 0
            run_agent(config)
            mock_sender.assert_called_once_with(config)

    def test_run_agent_receiver_calls_receiver_workflow(self) -> None:
        """run_agent routes receiver mode to receiver workflow."""
        config = self._make_config(mode="receiver")

        with patch("redwood_dataagent.agent._create_receiver_workflow") as mock_receiver:
            mock_receiver.return_value = 0
            run_agent(config)
            mock_receiver.assert_called_once_with(config)

    def test_run_agent_invalid_mode_raises_error(self) -> None:
        """run_agent raises error for invalid agent mode."""
        config = self._make_config(mode="invalid")  # type: ignore

        with pytest.raises(Exception):
            run_agent(config)

    def test_run_agent_propagates_sender_exit_code(self) -> None:
        """run_agent propagates exit code from sender workflow."""
        config = self._make_config(mode="sender")

        with patch("redwood_dataagent.agent._create_sender_workflow") as mock_sender:
            mock_sender.return_value = 42
            exit_code = run_agent(config)
            assert exit_code == 42

    def test_run_agent_propagates_receiver_exit_code(self) -> None:
        """run_agent propagates exit code from receiver workflow."""
        config = self._make_config(mode="receiver")

        with patch("redwood_dataagent.agent._create_receiver_workflow") as mock_receiver:
            mock_receiver.return_value = 42
            exit_code = run_agent(config)
            assert exit_code == 42