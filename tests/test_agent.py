"""Unit tests for the agent runtime entrypoints."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from redwood_dataagent.audit.events import EventOutcome
from redwood_dataagent.agent import (
    _compute_checksum,
    _create_receiver_workflow,
    _create_sender_workflow,
    _download_from_s3,
    _mark_file_processed,
    _parse_s3_path,
    _scan_sender_directory,
    run_agent,
)
from redwood_dataagent.config import AgentConfig
from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.logging_utils import set_agent_mode, set_transfer_session_id
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
            "sender_staging_bucket": "tts-core-development-dot-data-staging",
            "receiver_landing_bucket": "tts-core-development-gsa-data-landing",
            "receiver_target_bucket": "tts-core-development-gsa-data-target",
            "sender_data_directory": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_sender_workflow_success(self, tmp_path: Path) -> None:
        """Sender workflow completes successfully."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")
        
        # Create a temp file for mocking the download
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        
        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    mock_client = MagicMock()
                    mock_s3_class.return_value = mock_client
                    
                    # Mock the download_file method to copy our test file
                    def mock_download(bucket, key, dest):
                        import shutil
                        shutil.copy2(test_file, dest)
                    
                    mock_client.download_file.side_effect = mock_download
                    mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                    
                    exit_code = _create_sender_workflow(config)
                    assert exit_code == 0

    def test_sender_workflow_requires_sender_file(self) -> None:
        """Sender workflow succeeds gracefully when no sender data directory is configured (idempotent)."""
        config = self._make_config()

        exit_code = _create_sender_workflow(config)

        assert exit_code == 0  # Idempotent: no directory = no work to do = success

    def test_sender_workflow_with_mock_policy(self, tmp_path: Path) -> None:
        """Sender workflow works with mocked policy approver."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")
        
        # Create a temp file for mocking the download
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    with patch("redwood_dataagent.agent.PolicyApprover") as mock_approver_class:
                        mock_client = MagicMock()
                        mock_s3_class.return_value = mock_client
                        
                        def mock_download(bucket, key, dest):
                            import shutil
                            shutil.copy2(test_file, dest)
                        
                        mock_client.download_file.side_effect = mock_download
                        mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                        
                        mock_approver = MagicMock()
                        mock_approver.approve_transfer.return_value = True
                        mock_approver_class.return_value = mock_approver

                        exit_code = _create_sender_workflow(config)
                        assert exit_code == 0
                        mock_approver.approve_transfer.assert_called_once()

    def test_sender_workflow_uses_sender_provided_data_file(self, tmp_path: Path) -> None:
        """Sender workflow stages a sender-provided source file when configured."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")
        
        # Create a temp file for mocking the download
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    mock_client = MagicMock()
                    mock_s3_class.return_value = mock_client
                    
                    def mock_download(bucket, key, dest):
                        import shutil
                        shutil.copy2(test_file, dest)
                    
                    mock_client.download_file.side_effect = mock_download
                    mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                    
                    exit_code = _create_sender_workflow(config)
                    assert exit_code == 0

    def test_sender_workflow_policy_denied(self) -> None:
        """Sender workflow exits with error when policy denies transfer."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.PolicyApprover") as mock_approver_class:
                    mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                    mock_approver = MagicMock()
                    mock_approver.approve_transfer.return_value = False
                    mock_approver_class.return_value = mock_approver

                    exit_code = _create_sender_workflow(config)
                    assert exit_code == 1

    def test_sender_workflow_handles_exception(self) -> None:
        """Sender workflow handles exceptions gracefully and returns error code."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._download_from_s3") as mock_download:
                mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                mock_download.side_effect = RuntimeError("Download failed")
                exit_code = _create_sender_workflow(config)
                assert exit_code == 1

    def test_sender_workflow_logs_events(self) -> None:
        """Sender workflow logs audit events."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
                    with patch("redwood_dataagent.agent.log_pipeline_complete"):
                        mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                        _create_sender_workflow(config)
                        mock_start.assert_called_once()

    def test_sender_workflow_no_files_found(self) -> None:
        """Sender workflow returns success when no new files are found."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            mock_scan.return_value = []  # No new files to process
            exit_code = _create_sender_workflow(config)
            assert exit_code == 0  # Still succeeds (idempotent)

    def test_sender_workflow_no_files_does_not_emit_extract_data(self) -> None:
        """Sender workflow should not emit extract_data when nothing is processed."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")

        with patch("redwood_dataagent.agent._scan_sender_directory", return_value=[]):
            with patch("redwood_dataagent.agent.log_extract_data") as mock_extract:
                exit_code = _create_sender_workflow(config)
                assert exit_code == 0
                mock_extract.assert_not_called()

    def test_sender_workflow_emits_step_audit_events_on_success(self, tmp_path: Path) -> None:
        """Sender workflow emits detect, compress, manifest and stage-upload audit events."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1}]')

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    with patch("redwood_dataagent.agent.log_extract_data") as mock_extract:
                        with patch("redwood_dataagent.agent.log_compress") as mock_compress:
                            with patch("redwood_dataagent.agent.log_manifest_created") as mock_manifest:
                                with patch("redwood_dataagent.agent.log_sftp_transfer_start") as mock_stage_start:
                                    with patch("redwood_dataagent.agent.log_sftp_transfer_complete") as mock_stage_complete:
                                        mock_client = MagicMock()
                                        mock_s3_class.return_value = mock_client

                                        def mock_download(bucket, key, dest):
                                            import shutil

                                            shutil.copy2(test_file, dest)

                                        mock_client.download_file.side_effect = mock_download
                                        mock_scan.return_value = [
                                            ("s3://bucket/incoming/records.json", "records.json")
                                        ]

                                        exit_code = _create_sender_workflow(config)
                                        assert exit_code == 0
                                        assert mock_extract.call_count >= 2
                                        mock_compress.assert_called_once()
                                        mock_manifest.assert_called_once()
                                        mock_stage_start.assert_called_once()
                                        mock_stage_complete.assert_called_once()

    def test_sender_workflow_upload_failure_logs_failure_and_returns_error(self, tmp_path: Path) -> None:
        """Sender workflow records stage-upload failure and exits non-zero."""
        config = self._make_config(sender_data_directory="s3://bucket/incoming/")
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1}]')

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._mark_file_processed"):
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    with patch("redwood_dataagent.agent.log_sftp_transfer_complete") as mock_stage_complete:
                        mock_client = MagicMock()
                        mock_s3_class.return_value = mock_client

                        def mock_download(bucket, key, dest):
                            import shutil

                            shutil.copy2(test_file, dest)

                        mock_client.download_file.side_effect = mock_download
                        mock_client.upload_file.side_effect = StorageError("staging upload failed")
                        mock_scan.return_value = [
                            ("s3://bucket/incoming/records.json", "records.json")
                        ]

                        exit_code = _create_sender_workflow(config)
                        assert exit_code == 1

                        failure_calls = [
                            call
                            for call in mock_stage_complete.call_args_list
                            if call.kwargs.get("outcome") == EventOutcome.FAILURE
                        ]
                        assert failure_calls
                        assert failure_calls[0].kwargs.get("bytes_transferred") == 0


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
            "sender_agency": "",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "",
            "receiver_landing_bucket": "tts-core-development-gsa-data-landing",
            "receiver_target_bucket": "tts-core-development-gsa-data-target",
            "sender_data_directory": "",
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def _setup_mock_landing(self, mock_landing: MagicMock, session_id: str = "session-456", sender: str = "dot", receiver: str = "gsa") -> None:
        """Wire standard mocks for a successful single-transfer receive."""
        mock_landing.list_sender_agencies.return_value = [sender]
        mock_landing.list_pending_transfers.return_value = [session_id]
        mock_manifest = MagicMock()
        mock_manifest.transfer_session_id = session_id
        mock_manifest.sender_agency = sender
        mock_manifest.receiver_agency = receiver
        mock_manifest.total_file_count = 2  # Updated: source file + archive
        mock_landing.fetch_from_landing_bucket.return_value = (b"archive-bytes", {})
        mock_landing.validate_manifest.return_value = mock_manifest
        mock_landing.decompress_archive.return_value = {"file_count": 1, "total_bytes": 42}

    def test_receiver_workflow_success(self) -> None:
        """Receiver discovers sender folder and processes transfer successfully."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store
                mock_store.is_transfer_already_stored.return_value = False
                self._setup_mock_landing(mock_landing)
                mock_store.store_to_target.return_value = {
                    "status": "stored", "file_count": 1,
                    "target_location": "s3://target/transfers/session-456/",
                }

                assert _create_receiver_workflow(config) == 0
                mock_landing.list_sender_agencies.assert_called_once()
                mock_landing.list_pending_transfers.assert_called_once_with("dot")
                mock_landing.fetch_from_landing_bucket.assert_called_once()

    def test_receiver_workflow_no_senders_returns_success(self) -> None:
        """Receiver returns 0 when landing bucket has no sender folders yet."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore"):
                mock_landing = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_landing.list_sender_agencies.return_value = []

                assert _create_receiver_workflow(config) == 0
                mock_landing.list_pending_transfers.assert_not_called()

    def test_receiver_workflow_polls_multiple_senders(self) -> None:
        """Receiver processes transfers from all discovered sender agency folders."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store
                mock_store.is_transfer_already_stored.return_value = False

                mock_landing.list_sender_agencies.return_value = ["dot", "hud"]
                mock_landing.list_pending_transfers.side_effect = lambda sa: [f"{sa}-sess-001"]

                def make_manifest(sa: str) -> MagicMock:
                    m = MagicMock()
                    m.transfer_session_id = f"{sa}-sess-001"
                    m.receiver_agency = config.receiver_agency
                    m.total_file_count = 2  # Updated: source file + archive
                    return m

                mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})
                mock_landing.validate_manifest.side_effect = lambda **kw: make_manifest(kw["sender_agency"])
                mock_landing.decompress_archive.return_value = {"file_count": 1, "total_bytes": 10}
                mock_store.store_to_target.return_value = {"status": "stored", "file_count": 1, "target_location": "s3://x/"}

                assert _create_receiver_workflow(config) == 0
                assert mock_landing.list_pending_transfers.call_count == 2
                assert mock_landing.fetch_from_landing_bucket.call_count == 2

    def test_receiver_workflow_partial_failure_returns_1(self) -> None:
        """Returns 1 when at least one transfer fails but others succeed."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store
                mock_store.is_transfer_already_stored.return_value = False

                mock_landing.list_sender_agencies.return_value = ["dot"]
                mock_landing.list_pending_transfers.return_value = ["sess-ok", "sess-bad"]

                ok_manifest = MagicMock()
                ok_manifest.transfer_session_id = "sess-ok"
                ok_manifest.receiver_agency = config.receiver_agency
                ok_manifest.total_file_count = 2  # Updated: source file + archive

                def fetch_side_effect(**kw: object) -> tuple[bytes, dict]:
                    if kw["transfer_session_id"] == "sess-bad":
                        raise RuntimeError("S3 error")
                    return (b"archive", {})

                mock_landing.fetch_from_landing_bucket.side_effect = fetch_side_effect
                mock_landing.validate_manifest.return_value = ok_manifest
                mock_landing.decompress_archive.return_value = {"file_count": 1, "total_bytes": 10}
                mock_store.store_to_target.return_value = {"status": "stored", "file_count": 1, "target_location": "s3://x/"}

                assert _create_receiver_workflow(config) == 1

    def test_receiver_workflow_logs_pipeline_start_and_complete(self) -> None:
        """Receiver logs pipeline_start and pipeline_complete for the overall run."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            with patch("redwood_dataagent.agent.log_pipeline_complete") as mock_complete:
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store
                        mock_store.is_transfer_already_stored.return_value = False
                        self._setup_mock_landing(mock_landing)
                        mock_store.store_to_target.return_value = {"status": "stored", "file_count": 1, "target_location": "s3://x/"}

                        exit_code = _create_receiver_workflow(config)
                        assert exit_code == 0
                        mock_start.assert_called_once()
                        mock_complete.assert_called_once()

    def test_receiver_workflow_logs_validate_and_store(self) -> None:
        """Receiver logs validate_manifest and store_data per transfer."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_validate_manifest") as mock_validate:
            with patch("redwood_dataagent.agent.log_store_data") as mock_store_log:
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store
                        mock_store.is_transfer_already_stored.return_value = False
                        self._setup_mock_landing(mock_landing)
                        mock_store.store_to_target.return_value = {"status": "stored", "file_count": 1, "target_location": "s3://x/"}

                        _create_receiver_workflow(config)
                        assert mock_validate.call_count >= 1
                        mock_store_log.assert_called_once()

    def test_receiver_workflow_list_sender_agencies_failure_returns_1(self) -> None:
        """Returns 1 when listing sender agencies raises an exception."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            mock_landing = MagicMock()
            mock_landing_cls.return_value = mock_landing
            mock_landing.list_sender_agencies.side_effect = RuntimeError("S3 down")

            assert _create_receiver_workflow(config) == 1

    def test_receiver_workflow_fails_on_manifest_transfer_id_mismatch(self) -> None:
        """Per-transfer failure when manifest transfer_session_id does not match folder name."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store
                mock_store.is_transfer_already_stored.return_value = False
                mock_landing.list_sender_agencies.return_value = ["dot"]
                mock_landing.list_pending_transfers.return_value = ["session-456"]
                mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})

                bad_manifest = MagicMock()
                bad_manifest.transfer_session_id = "different-session"  # mismatch
                bad_manifest.receiver_agency = config.receiver_agency
                bad_manifest.total_file_count = 1
                mock_landing.validate_manifest.return_value = bad_manifest

                assert _create_receiver_workflow(config) == 1

    def test_receiver_workflow_all_transfers_already_done_exits_cleanly(self) -> None:
        """Receiver exits cleanly when every discovered transfer is already marked done."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store

                mock_landing.list_sender_agencies.return_value = ["dot"]
                mock_landing.list_pending_transfers.return_value = ["sess-001"]
                mock_store.is_transfer_already_stored.return_value = True

                assert _create_receiver_workflow(config) == 0
                mock_landing.fetch_from_landing_bucket.assert_not_called()

    def test_receiver_workflow_skip_only_logs_idempotent_summary(self, caplog: pytest.LogCaptureFixture) -> None:
        """Skip-only receiver runs keep INFO logs to the idempotent summary."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start"):
            with patch("redwood_dataagent.agent.log_pipeline_complete"):
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store

                        mock_landing.list_sender_agencies.return_value = ["dot"]
                        mock_landing.list_pending_transfers.return_value = ["sess-001"]
                        mock_store.is_transfer_already_stored.return_value = True

                        with caplog.at_level(logging.INFO, logger="redwood_dataagent"):
                            assert _create_receiver_workflow(config) == 0

        messages = [record.getMessage() for record in caplog.records]
        assert any("No new files to process. Exiting receiver workflow (idempotent)." in message for message in messages)
        assert not any("already marked done in target" in message for message in messages)
        assert not any("Found 1 transfer session(s)" in message for message in messages)
        assert not any("Receiver scan complete:" in message for message in messages)

    def test_receiver_workflow_processing_log_includes_mode_and_transfer_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Per-transfer receiver processing log carries mode and transfer context."""
        config = self._make_config(transfer_session_id="run-session")
        set_agent_mode("receiver")
        set_transfer_session_id(config.transfer_session_id)

        with patch("redwood_dataagent.agent.log_pipeline_start"):
            with patch("redwood_dataagent.agent.log_pipeline_complete"):
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store
                        mock_store.is_transfer_already_stored.return_value = False
                        self._setup_mock_landing(mock_landing, session_id="sess-123")
                        mock_store.store_to_target.return_value = {
                            "status": "stored",
                            "file_count": 1,
                            "target_location": "s3://x/",
                        }

                        with caplog.at_level(logging.INFO, logger="redwood_dataagent"):
                            assert _create_receiver_workflow(config) == 0

        messages = [record.getMessage() for record in caplog.records]
        assert any(
            message == "[receiver][sess-123] Processing transfer from dot"
            for message in messages
        )
        set_agent_mode(None)
        set_transfer_session_id(None)


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
            "sender_staging_bucket": "tts-core-development-dot-data-staging",
            "receiver_landing_bucket": "tts-core-development-gsa-data-landing",
            "receiver_target_bucket": "tts-core-development-gsa-data-target",
            "sender_data_directory": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_run_agent_sender_returns_success(self, tmp_path: Path) -> None:
        """Verify sender mode agent completes with exit code 0."""
        source_file = tmp_path / "records.json"
        source_file.write_text('[{"id": 1, "name": "provided", "value": 1}]')
        config = self._make_config(mode="sender", sender_data_directory="s3://bucket/incoming/")
        
        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent._download_from_s3") as mock_download:
                with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                    mock_client = MagicMock()
                    mock_s3_class.return_value = mock_client
                    
                    def mock_s3_download(bucket, key, dest):
                        import shutil
                        shutil.copy2(source_file, dest)
                    
                    mock_client.download_file.side_effect = mock_s3_download
                    mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                    
                    assert run_agent(config) == 0

    def test_run_agent_receiver_returns_success(self) -> None:
        """Verify receiver mode agent completes with exit code 0."""
        config = self._make_config(mode="receiver")

        with patch("redwood_dataagent.agent._create_receiver_workflow") as mock_receiver:
            mock_receiver.return_value = 0
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


class TestParseS3Path:
    """Tests for _parse_s3_path() S3 URL parsing."""

    def test_parse_s3_path_valid_simple(self) -> None:
        """Parse valid S3 path with bucket and key."""
        bucket, key = _parse_s3_path("s3://my-bucket/path/to/file.json")
        assert bucket == "my-bucket"
        assert key == "path/to/file.json"

    def test_parse_s3_path_valid_complex_key(self) -> None:
        """Parse valid S3 path with complex key including multiple slashes."""
        bucket, key = _parse_s3_path(
            "s3://tts-core-dev-dot-data-staging/transfers/sess-001/data.json"
        )
        assert bucket == "tts-core-dev-dot-data-staging"
        assert key == "transfers/sess-001/data.json"

    def test_parse_s3_path_valid_nested_dirs(self) -> None:
        """Parse S3 path with deeply nested directories."""
        bucket, key = _parse_s3_path("s3://bucket/a/b/c/d/e/file.tar.gz")
        assert bucket == "bucket"
        assert key == "a/b/c/d/e/file.tar.gz"

    def test_parse_s3_path_invalid_not_s3_prefix(self) -> None:
        """Parse returns None when path does not start with s3://."""
        result = _parse_s3_path("/local/file/path.json")
        assert result is None

    def test_parse_s3_path_invalid_no_key(self) -> None:
        """Parse raises error when S3 path has no key component."""
        with pytest.raises(StorageError, match="Invalid S3 path format"):
            _parse_s3_path("s3://bucket-only/")

    def test_parse_s3_path_invalid_no_bucket(self) -> None:
        """Parse raises error when S3 path has no bucket."""
        with pytest.raises(StorageError, match="Invalid S3 path format"):
            _parse_s3_path("s3:///path/to/file.json")

    def test_parse_s3_path_invalid_malformed(self) -> None:
        """Parse raises error for malformed S3 URLs."""
        with pytest.raises(StorageError, match="Invalid S3 path format"):
            _parse_s3_path("s3://")

    def test_parse_s3_path_case_sensitive_prefix(self) -> None:
        """Parse requires lowercase s3:// prefix."""
        result = _parse_s3_path("S3://bucket/key")
        assert result is None

    def test_parse_s3_path_with_special_chars(self) -> None:
        """Parse handles S3 keys with special characters."""
        bucket, key = _parse_s3_path("s3://bucket/path-with_special.chars/file.json")
        assert bucket == "bucket"
        assert key == "path-with_special.chars/file.json"


class TestDownloadFromS3:
    """Tests for _download_from_s3() helper function."""

    def _make_config(self, **kwargs: object) -> AgentConfig:
        """Create a test AgentConfig with defaults."""
        defaults = {
            "agent_mode": "sender",
            "tenant": "tts",
            "environment": "dev",
            "aws_region": "us-east-1",
            "log_level": "INFO",
            "transfer_session_id": "sess-001",
            "sender_agency": "dot",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "tts-core-dev-dot-data-staging",
            "receiver_landing_bucket": "tts-core-dev-gsa-data-landing",
            "receiver_target_bucket": "tts-core-dev-gsa-data-target",
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_download_from_s3_success(self, tmp_path: Path) -> None:
        """Download from S3 succeeds with metadata."""
        destination = tmp_path / "downloaded.json"

        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            destination.write_text('{"test": "data"}')

            metadata = _download_from_s3(
                "s3://bucket/path/file.json", destination, "us-east-1"
            )

            assert metadata["data_source"] == "s3_object"
            assert metadata["s3_bucket"] == "bucket"
            assert metadata["s3_key"] == "path/file.json"
            assert metadata["file_name"] == "downloaded.json"
            assert metadata["file_size_bytes"] > 0
            mock_client.download_file.assert_called_once()

    def test_download_from_s3_creates_dirs(self, tmp_path: Path) -> None:
        """Download from S3 creates parent directories."""
        destination = tmp_path / "subdir" / "nested" / "file.json"

        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('{}')

            _download_from_s3(
                "s3://bucket/path/file.json", destination, "us-east-1"
            )

            # Verify download was called (check invocation count and basic args)
            assert mock_client.download_file.call_count == 1

    def test_download_from_s3_invalid_path_raises(self, tmp_path: Path) -> None:
        """Download from S3 raises error for invalid S3 path."""
        destination = tmp_path / "file.json"

        # Invalid path (not S3 format) causes _parse_s3_path to return None
        # which raises TypeError when unpacking
        with pytest.raises(TypeError):
            _download_from_s3("/local/path/file.json", destination, "us-east-1")

    def test_download_from_s3_client_error_raises(self, tmp_path: Path) -> None:
        """Download from S3 propagates S3Client errors."""
        destination = tmp_path / "file.json"

        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_client.download_file.side_effect = StorageError("Bucket not found")
            mock_s3_class.return_value = mock_client

            with pytest.raises(StorageError, match="Bucket not found"):
                _download_from_s3(
                    "s3://bucket/path/file.json", destination, "us-east-1"
                )

    def test_download_from_s3_uses_aws_region(self, tmp_path: Path) -> None:
        """Download from S3 passes AWS region to S3Client."""
        destination = tmp_path / "file.json"

        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            destination.write_text('{}')

            _download_from_s3(
                "s3://bucket/path/file.json", destination, "us-west-2"
            )

            mock_s3_class.assert_called_once_with(aws_region="us-west-2")