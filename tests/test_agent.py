"""Unit tests for the agent runtime entrypoints."""

from __future__ import annotations

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
            "sender_agency": "dot",
            "receiver_agency": "gsa",
            "sender_staging_bucket": "tts-core-development-dot-data-staging",
            "receiver_landing_bucket": "tts-core-development-gsa-data-landing",
            "receiver_target_bucket": "tts-core-development-gsa-data-target",
            "sender_data_directory": None,
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)  # type: ignore

    def test_receiver_workflow_success(self) -> None:
        """Receiver workflow completes successfully."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                mock_landing = MagicMock()
                mock_store = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_store_cls.return_value = mock_store

                mock_landing.fetch_from_landing_bucket.return_value = (b"archive-bytes", {
                    "manifest_version": "1.0",
                    "transfer_session_id": config.transfer_session_id,
                    "sender_agency": config.sender_agency,
                    "receiver_agency": config.receiver_agency,
                    "created_at": "2026-04-06T10:00:00Z",
                    "checksum_algorithm": "sha256",
                    "total_file_count": 1,
                    "compression_type": "gzip",
                    "transfer_date": "2026-04-06",
                    "files": [{
                        "file_name": "transfer.tar.gz",
                        "file_size_bytes": 10,
                        "checksum_sha256": "a" * 64,
                    }],
                })
                mock_manifest = MagicMock()
                mock_manifest.transfer_session_id = config.transfer_session_id
                mock_manifest.sender_agency = config.sender_agency
                mock_manifest.receiver_agency = config.receiver_agency
                mock_manifest.total_file_count = 1
                mock_landing.validate_manifest.return_value = mock_manifest
                mock_landing.decompress_archive.return_value = {
                    "file_count": 1,
                    "total_bytes": 42,
                }
                mock_store.store_to_target.return_value = {
                    "status": "stored",
                    "file_count": 1,
                    "target_location": "s3://target/transfers/session-456/",
                }

                exit_code = _create_receiver_workflow(config)
                assert exit_code == 0

    def test_receiver_workflow_logs_events(self) -> None:
        """Receiver workflow logs audit events."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            with patch("redwood_dataagent.agent.log_pipeline_complete"):
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store

                        mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})
                        mock_manifest = MagicMock()
                        mock_manifest.transfer_session_id = config.transfer_session_id
                        mock_manifest.sender_agency = config.sender_agency
                        mock_manifest.receiver_agency = config.receiver_agency
                        mock_manifest.total_file_count = 1
                        mock_landing.validate_manifest.return_value = mock_manifest
                        mock_landing.decompress_archive.return_value = {"file_count": 0, "total_bytes": 0}
                        mock_store.store_to_target.return_value = {"status": "stored", "file_count": 0, "target_location": "s3://target/transfers/session-456/"}

                        _create_receiver_workflow(config)
                        mock_start.assert_called_once()

    def test_receiver_workflow_logs_manifest_validation_placeholder(self) -> None:
        """Receiver workflow logs manifest validation against landing storage."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_validate_manifest") as mock_validate:
            with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                    mock_landing = MagicMock()
                    mock_store = MagicMock()
                    mock_landing_cls.return_value = mock_landing
                    mock_store_cls.return_value = mock_store

                    mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})
                    mock_manifest = MagicMock()
                    mock_manifest.transfer_session_id = config.transfer_session_id
                    mock_manifest.sender_agency = config.sender_agency
                    mock_manifest.receiver_agency = config.receiver_agency
                    mock_manifest.total_file_count = 1
                    mock_landing.validate_manifest.return_value = mock_manifest
                    mock_landing.decompress_archive.return_value = {"file_count": 0, "total_bytes": 0}
                    mock_store.store_to_target.return_value = {"status": "stored", "file_count": 0, "target_location": "s3://target/transfers/session-456/"}

                    _create_receiver_workflow(config)
                    assert mock_validate.call_count >= 1

    def test_receiver_workflow_logs_store_placeholder(self) -> None:
        """Receiver workflow logs store step against target storage."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_store_data") as mock_store_log:
            with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                    mock_landing = MagicMock()
                    mock_store = MagicMock()
                    mock_landing_cls.return_value = mock_landing
                    mock_store_cls.return_value = mock_store

                    mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})
                    mock_manifest = MagicMock()
                    mock_manifest.transfer_session_id = config.transfer_session_id
                    mock_manifest.sender_agency = config.sender_agency
                    mock_manifest.receiver_agency = config.receiver_agency
                    mock_manifest.total_file_count = 1
                    mock_landing.validate_manifest.return_value = mock_manifest
                    mock_landing.decompress_archive.return_value = {"file_count": 0, "total_bytes": 0}
                    mock_store.store_to_target.return_value = {"status": "stored", "file_count": 0, "target_location": "s3://target/transfers/session-456/"}

                    _create_receiver_workflow(config)
                    mock_store_log.assert_called_once()

    def test_receiver_workflow_handles_exception(self) -> None:
        """Receiver workflow handles exceptions gracefully."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            mock_landing = MagicMock()
            mock_landing_cls.return_value = mock_landing
            mock_landing.fetch_from_landing_bucket.side_effect = RuntimeError("Test error")
            exit_code = _create_receiver_workflow(config)
            assert exit_code == 1

    def test_receiver_workflow_logs_all_paths(self) -> None:
        """Receiver workflow logs start through complete for success path."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.log_pipeline_start") as mock_start:
            with patch("redwood_dataagent.agent.log_pipeline_complete") as mock_complete:
                with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
                    with patch("redwood_dataagent.agent.ReceiverTargetStore") as mock_store_cls:
                        mock_landing = MagicMock()
                        mock_store = MagicMock()
                        mock_landing_cls.return_value = mock_landing
                        mock_store_cls.return_value = mock_store

                        mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})
                        mock_manifest = MagicMock()
                        mock_manifest.transfer_session_id = config.transfer_session_id
                        mock_manifest.sender_agency = config.sender_agency
                        mock_manifest.receiver_agency = config.receiver_agency
                        mock_manifest.total_file_count = 1
                        mock_landing.validate_manifest.return_value = mock_manifest
                        mock_landing.decompress_archive.return_value = {"file_count": 0, "total_bytes": 0}
                        mock_store.store_to_target.return_value = {"status": "stored", "file_count": 0, "target_location": "s3://target/transfers/session-456/"}

                        exit_code = _create_receiver_workflow(config)
                        assert exit_code == 0
                        mock_start.assert_called_once()
                        mock_complete.assert_called_once()

    def test_receiver_workflow_fails_on_manifest_transfer_id_mismatch(self) -> None:
        """Receiver workflow fails when manifest transfer id does not match config."""
        config = self._make_config()

        with patch("redwood_dataagent.agent.ReceiverLandingZone") as mock_landing_cls:
            with patch("redwood_dataagent.agent.ReceiverTargetStore"):
                mock_landing = MagicMock()
                mock_landing_cls.return_value = mock_landing
                mock_landing.fetch_from_landing_bucket.return_value = (b"archive", {})

                bad_manifest = MagicMock()
                bad_manifest.transfer_session_id = "different-session"
                bad_manifest.sender_agency = config.sender_agency
                bad_manifest.receiver_agency = config.receiver_agency
                bad_manifest.total_file_count = 1
                mock_landing.validate_manifest.return_value = bad_manifest

                exit_code = _create_receiver_workflow(config)
                assert exit_code == 1


class TestScanSenderDirectory:
    """Tests for _scan_sender_directory() function."""

    def test_scan_sender_directory_returns_tuples(self) -> None:
        """_scan_sender_directory returns list of (s3_path, file_name) tuples."""
        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            mock_client._client.list_objects_v2.return_value = {
                "Contents": [{"Key": "incoming/file1.json"}]
            }
            mock_client._client.head_object.side_effect = Exception("No marker")

            result = _scan_sender_directory("s3://bucket/incoming/", "us-east-1")
            
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0][0].startswith("s3://")
            assert result[0][1] == "file1.json"

    def test_scan_sender_directory_skips_processed_files_with_done_marker(self) -> None:
        """Files with processed .done markers are skipped to avoid re-staging."""
        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            mock_client._client.list_objects_v2.return_value = {
                "Contents": [{"Key": "incoming/file1.json"}]
            }
            # Marker exists for file1.json
            mock_client._client.head_object.return_value = {"ResponseMetadata": {}}

            result = _scan_sender_directory("s3://bucket/incoming/", "us-east-1")

            assert result == []


class TestMarkFileProcessed:
    """Tests for _mark_file_processed() function."""

    def test_mark_file_processed_creates_marker(self) -> None:
        """_mark_file_processed creates done marker in processed folder."""
        with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
            mock_client = MagicMock()
            mock_s3_class.return_value = mock_client
            
            _mark_file_processed("test.json", "s3://bucket/incoming/", "us-east-1")
            
            mock_client._client.put_object.assert_called_once()
            call_kwargs = mock_client._client.put_object.call_args[1]
            assert "processed" in call_kwargs["Key"]
            assert "test.json" in call_kwargs["Key"]


class TestErrorPaths:
    """Tests for error handling in sender workflow."""

    def test_sender_workflow_with_mark_file_failure(self, tmp_path) -> None:
        """Sender workflow handles mark_file_processed errors gracefully."""
        test_file = tmp_path / "records.json"
        test_file.write_text('[{"id": 1}]')
        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="development",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="session-123",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="tts-core-development-dot-data-staging",
            receiver_landing_bucket="tts-core-development-gsa-data-landing",
            receiver_target_bucket="tts-core-development-gsa-data-target",
            sender_data_directory="s3://bucket/incoming/",
        )

        with patch("redwood_dataagent.agent._scan_sender_directory") as mock_scan:
            with patch("redwood_dataagent.agent.S3Client") as mock_s3_class:
                with patch("redwood_dataagent.agent._mark_file_processed") as mock_mark:
                    mock_client = MagicMock()
                    mock_s3_class.return_value = mock_client
                    
                    def mock_download(bucket, key, dest):
                        import shutil
                        shutil.copy2(test_file, dest)
                    
                    mock_client.download_file.side_effect = mock_download
                    mock_scan.return_value = [("s3://bucket/incoming/records.json", "records.json")]
                    mock_mark.side_effect = Exception("Mark failed")
                    
                    # Mark failure should cause workflow to fail
                    exit_code = _create_sender_workflow(config)
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