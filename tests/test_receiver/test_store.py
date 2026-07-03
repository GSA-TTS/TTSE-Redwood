"""Tests for receiver target store functionality.

Tests cover:
- S3 target store success and error cases
- Idempotency tracking via marker objects
- File structure preservation
- Audit logging
"""

import json
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from redwood_dataagent.aws.s3 import S3Client
from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.receiver.store import ReceiverTargetStore


@pytest.fixture
def mock_s3_client():
    """Mock S3Client instance."""
    client = mock.MagicMock(spec=S3Client)
    client._client = mock.MagicMock()
    return client


@pytest.fixture
def receiver_target_store(mock_s3_client):
    """Create ReceiverTargetStore instance with mocked S3."""
    return ReceiverTargetStore(
        s3_client=mock_s3_client,
        target_bucket="tts-core-dev-gsa-data-target",
        environment="dev",
    )


@pytest.fixture
def sample_extracted_files(tmp_path):
    """Create sample extracted files for testing."""
    # Create directory structure
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    # Create sample files
    (extract_dir / "file1.txt").write_text("content1")
    (extract_dir / "file2.csv").write_text("data1,data2\nvalue1,value2")

    # Create nested directory
    nested_dir = extract_dir / "subdir"
    nested_dir.mkdir()
    (nested_dir / "file3.json").write_text('{"key": "value"}')

    return extract_dir


class TestReceiverTargetStoreSuccess:
    """Tests for ReceiverTargetStore.store_to_target method - success paths."""

    def test_store_success(self, receiver_target_store, sample_extracted_files):
        """Test successful store of files to target S3."""
        # Mock S3 responses
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        result = receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert result["status"] == "stored"
        assert result["file_count"] == 3
        assert result["total_bytes"] > 0
        assert "target_location" in result
        assert "stored_at" in result

    def test_store_preserves_directory_structure(self, receiver_target_store, sample_extracted_files):
        """Test that directory structure is preserved in target bucket."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Check that put_object was called with correct keys
        calls = receiver_target_store.s3_client._client.put_object.call_args_list

        # Should have been called for: file1.txt, file2.csv, file3.json, .done marker
        expected_keys = [
            "transfers/dot/transfer-20260407-001/file1.txt",
            "transfers/dot/transfer-20260407-001/file2.csv",
            "transfers/dot/transfer-20260407-001/subdir/file3.json",
            "processed/dot/transfer-20260407-001.done",
        ]

        actual_keys = [call.kwargs["Key"] for call in calls]
        for expected_key in expected_keys:
            assert expected_key in actual_keys

    def test_store_creates_marker_object(self, receiver_target_store, sample_extracted_files):
        """Test that marker object is created for idempotency."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Find the marker put_object call
        marker_call = None
        for call in receiver_target_store.s3_client._client.put_object.call_args_list:
            if call.kwargs["Key"] == "processed/dot/transfer-20260407-001.done":
                marker_call = call
                break

        assert marker_call is not None
        marker_body = marker_call.kwargs["Body"].decode("utf-8")
        marker_data = json.loads(marker_body)

        assert marker_data["transfer_id"] == "transfer-20260407-001"
        assert marker_data["file_count"] == 3
        assert "stored_at" in marker_data


class TestReceiverTargetStoreIdempotency:
    """Tests for idempotency tracking via marker objects."""

    def test_store_idempotency_skip_on_retry(self, receiver_target_store, sample_extracted_files):
        """Test that retry with same transfer_session_id skips re-upload."""
        # First attempt: marker doesn't exist
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        result1 = receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert result1["status"] == "stored"
        initial_put_count = receiver_target_store.s3_client._client.put_object.call_count

        # Second attempt: marker exists (idempotency)
        receiver_target_store.s3_client._client.head_object.side_effect = None
        receiver_target_store.s3_client._client.head_object.return_value = {"ContentLength": 100}

        result2 = receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert result2["status"] == "already_stored"
        # put_object should not be called again (only for marker creation on first attempt)
        assert receiver_target_store.s3_client._client.put_object.call_count == initial_put_count

    def test_store_idempotency_marker_key_check(self, receiver_target_store, sample_extracted_files):
        """Test that correct marker key is checked for idempotency."""
        receiver_target_store.s3_client._client.head_object.return_value = {"ContentLength": 100}
        receiver_target_store.s3_client._client.put_object.return_value = None

        receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Verify head_object was called with correct marker key
        receiver_target_store.s3_client._client.head_object.assert_called_once_with(
            Bucket="tts-core-dev-gsa-data-target", Key="processed/dot/transfer-20260407-001.done"
        )


class TestReceiverTargetStoreErrors:
    """Tests for error handling."""

    def test_store_s3_upload_error(self, receiver_target_store, sample_extracted_files):
        """Test handling of S3 upload errors."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.side_effect = Exception("AccessDenied")

        with pytest.raises(StorageError, match="Failed to.*upload"):
            receiver_target_store.store_to_target(
                extracted_files_dir=sample_extracted_files,
                transfer_session_id="transfer-20260407-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_store_marker_creation_error(self, receiver_target_store, sample_extracted_files):
        """Test handling of marker object creation errors."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")

        def put_object_side_effect(**kwargs):
            # First calls (files) succeed, marker creation fails
            if kwargs["Key"].endswith(".done"):
                raise Exception("AccessDenied on marker")
            return None

        receiver_target_store.s3_client._client.put_object.side_effect = put_object_side_effect

        with pytest.raises(StorageError, match="Failed to create marker"):
            receiver_target_store.store_to_target(
                extracted_files_dir=sample_extracted_files,
                transfer_session_id="transfer-20260407-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_store_nonexistent_directory(self, receiver_target_store):
        """Test that nonexistent directory results in 0 files stored."""
        # When directory doesn't exist, rglob returns empty and we get 0 files
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        result = receiver_target_store.store_to_target(
            extracted_files_dir=Path("/nonexistent/directory"),
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Should handle gracefully with 0 files
        assert result["status"] == "stored"
        assert result["file_count"] == 0
        assert result["total_bytes"] == 0


class TestReceiverTargetStoreMarkerObject:
    """Tests for marker object metadata format."""

    def test_marker_metadata_format(self, receiver_target_store, sample_extracted_files):
        """Test that marker object has correct metadata format."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Get the marker put_object call
        marker_call = None
        for call in receiver_target_store.s3_client._client.put_object.call_args_list:
            if call.kwargs["Key"].endswith(".done"):
                marker_call = call
                break

        assert marker_call is not None

        # Verify body is valid JSON
        body = marker_call.kwargs["Body"]
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        marker_data = json.loads(body)

        # Verify required fields
        assert marker_data["transfer_id"] == "transfer-20260407-001"
        assert marker_data["file_count"] == 3
        assert marker_data["total_bytes"] > 0
        assert "stored_at" in marker_data

        # Verify ISO format timestamp
        datetime.fromisoformat(marker_data["stored_at"])

    def test_marker_has_no_tagging(self, receiver_target_store, sample_extracted_files):
        """Test that marker object write does not require S3 object tagging."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Get the marker put_object call
        marker_call = None
        for call in receiver_target_store.s3_client._client.put_object.call_args_list:
            if call.kwargs["Key"].endswith(".done"):
                marker_call = call
                break

        assert marker_call is not None
        assert "Tagging" not in marker_call.kwargs


class TestReceiverTargetStoreFileHandling:
    """Tests for file handling and directory traversal."""

    def test_store_handles_empty_directories(self, receiver_target_store, tmp_path):
        """Test that empty directories are handled gracefully."""
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        # Create empty subdirectory
        (extract_dir / "empty_dir").mkdir()

        # Create one file
        (extract_dir / "file1.txt").write_text("content")

        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        result = receiver_target_store.store_to_target(
            extracted_files_dir=extract_dir,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Should only count actual files, not directories
        assert result["file_count"] == 1  # Only file1.txt

    def test_store_large_files(self, receiver_target_store, tmp_path):
        """Test storing large files."""
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        # Create a large file (1MB)
        large_file = extract_dir / "large_file.bin"
        large_file.write_bytes(b"x" * (1024 * 1024))

        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        result = receiver_target_store.store_to_target(
            extracted_files_dir=extract_dir,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert result["file_count"] == 1  # large_file only
        assert result["total_bytes"] >= (1024 * 1024)


class TestReceiverTargetStoreIntegration:
    """Integration tests for complete store workflow."""

    def test_complete_store_workflow(self, receiver_target_store, sample_extracted_files):
        """Test complete workflow: check idempotency, store, create marker."""
        receiver_target_store.s3_client._client.head_object.side_effect = Exception("NoSuchKey")
        receiver_target_store.s3_client._client.put_object.return_value = None

        # Execute store
        result = receiver_target_store.store_to_target(
            extracted_files_dir=sample_extracted_files,
            transfer_session_id="transfer-20260407-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Verify result
        assert result["status"] == "stored"
        assert result["file_count"] == 3
        assert result["target_location"] == "s3://tts-core-dev-gsa-data-target/transfers/dot/transfer-20260407-001/"

        # Verify S3 operations
        assert receiver_target_store.s3_client._client.head_object.called
        assert receiver_target_store.s3_client._client.put_object.called
