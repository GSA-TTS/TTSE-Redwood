"""Tests for receiver landing zone ingest functionality.

Tests cover:
- S3 landing bucket fetch success and error cases
- Manifest validation and checksum verification
- Archive decompression with various file structures
"""

import hashlib
import io
import json
import tarfile
from unittest import mock

import pytest

from redwood_dataagent.aws.s3 import S3Client
from redwood_dataagent.exceptions import ManifestValidationError, StorageError
from redwood_dataagent.receiver.landing import ReceiverLandingZone


@pytest.fixture
def mock_s3_client():
    """Mock S3Client instance."""
    client = mock.MagicMock(spec=S3Client)
    client._client = mock.MagicMock()
    return client


@pytest.fixture
def receiver_landing_zone(mock_s3_client):
    """Create ReceiverLandingZone instance with mocked S3."""
    return ReceiverLandingZone(
        s3_client=mock_s3_client,
        landing_bucket="gsa-data-dev-landing",
        environment="dev",
    )


@pytest.fixture
def sample_archive():
    """Create a sample tar.gz archive for testing."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        # Add sample file
        info = tarfile.TarInfo(name="sample.txt")
        info.size = 11
        tar.addfile(info, io.BytesIO(b"hello world"))
    return tar_buffer.getvalue()


@pytest.fixture
def sample_manifest(sample_archive):
    """Create a sample manifest for testing."""
    archive_checksum = hashlib.sha256(sample_archive).hexdigest()
    return {
        "manifest_version": "1.0",
        "transfer_session_id": "transfer-20260406-001",
        "sender_agency": "dot",
        "receiver_agency": "gsa",
        "created_at": "2026-04-06T10:00:00Z",
        "checksum_algorithm": "sha256",
        "total_file_count": 1,
        "compression_type": "gzip",
        "transfer_date": "2026-04-06",
        "files": [
            {
                "file_name": "transfer.tar.gz",
                "file_size_bytes": len(sample_archive),
                "checksum_sha256": archive_checksum,
            }
        ],
    }


class TestReceiverLandingZoneFetch:
    """Tests for ReceiverLandingZone.fetch_from_landing_bucket method."""

    def test_fetch_success(self, receiver_landing_zone, sample_archive, sample_manifest):
        """Test successful fetch of archive and manifest from S3 landing."""
        # Mock S3 responses
        manifest_bytes = json.dumps(sample_manifest).encode("utf-8")
        
        # Create mock response objects
        manifest_response = {"Body": mock.MagicMock()}
        manifest_response["Body"].read.return_value = manifest_bytes
        
        archive_response = {"Body": mock.MagicMock()}
        archive_response["Body"].read.return_value = sample_archive
        
        # Setup get_object to return manifest, then archive
        def get_object_side_effect(**kwargs):
            if "manifest.json" in kwargs["Key"]:
                return manifest_response
            elif "transfer.tar.gz" in kwargs["Key"]:
                return archive_response
            raise ValueError(f"Unexpected key: {kwargs['Key']}")
        
        receiver_landing_zone.s3_client._client.get_object.side_effect = get_object_side_effect

        archive_bytes, manifest_dict = receiver_landing_zone.fetch_from_landing_bucket(
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert archive_bytes == sample_archive
        assert manifest_dict["transfer_session_id"] == "transfer-20260406-001"
        assert receiver_landing_zone.s3_client._client.get_object.call_count == 2

    def test_fetch_missing_manifest(self, receiver_landing_zone):
        """Test fetch fails when manifest is not found in S3."""
        receiver_landing_zone.s3_client._client.get_object.side_effect = Exception(
            "NoSuchKey"
        )

        with pytest.raises(StorageError, match="Failed to download"):
            receiver_landing_zone.fetch_from_landing_bucket(
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_fetch_s3_error(self, receiver_landing_zone):
        """Test fetch fails on S3 error."""
        receiver_landing_zone.s3_client._client.get_object.side_effect = Exception(
            "AccessDenied"
        )

        with pytest.raises(StorageError, match="Failed to download"):
            receiver_landing_zone.fetch_from_landing_bucket(
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )


class TestReceiverLandingZoneValidate:
    """Tests for ReceiverLandingZone.validate_manifest method."""

    def test_validate_manifest_success(
        self, receiver_landing_zone, sample_archive, sample_manifest
    ):
        """Test successful manifest validation with matching checksum."""
        manifest = receiver_landing_zone.validate_manifest(
            manifest_dict=sample_manifest,
            archive_bytes=sample_archive,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert manifest.transfer_session_id == "transfer-20260406-001"
        assert manifest.sender_agency == "dot"
        assert manifest.receiver_agency == "gsa"

    def test_validate_manifest_checksum_mismatch(
        self, receiver_landing_zone, sample_archive, sample_manifest
    ):
        """Test validation fails when archive checksum doesn't match manifest."""
        # Corrupt the manifest checksum
        sample_manifest["files"][0]["checksum_sha256"] = (
            "0" * 64  # Invalid checksum
        )

        with pytest.raises(ManifestValidationError, match="checksum mismatch"):
            receiver_landing_zone.validate_manifest(
                manifest_dict=sample_manifest,
                archive_bytes=sample_archive,
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_validate_manifest_invalid_structure(self, receiver_landing_zone, sample_archive):
        """Test validation fails when manifest structure is invalid."""
        invalid_manifest = {"transfer_session_id": "transfer-001"}

        with pytest.raises(ManifestValidationError, match="validation failed"):
            receiver_landing_zone.validate_manifest(
                manifest_dict=invalid_manifest,
                archive_bytes=sample_archive,
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_validate_manifest_wrong_file_count(
        self, receiver_landing_zone, sample_archive, sample_manifest
    ):
        """Test validation fails when file count doesn't match."""
        # Add extra file entry
        sample_manifest["files"].append(
            {
                "file_name": "extra.txt",
                "file_size_bytes": 100,
                "checksum_sha256": "0" * 64,
            }
        )
        sample_manifest["total_file_count"] = 2

        with pytest.raises(ManifestValidationError):
            receiver_landing_zone.validate_manifest(
                manifest_dict=sample_manifest,
                archive_bytes=sample_archive,
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )


class TestReceiverLandingZoneDecompress:
    """Tests for ReceiverLandingZone.decompress_archive method."""

    def test_decompress_success(self, receiver_landing_zone, sample_archive, tmp_path):
        """Test successful archive decompression."""
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        metadata = receiver_landing_zone.decompress_archive(
            archive_bytes=sample_archive,
            target_directory=extract_dir,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert metadata["file_count"] == 1
        assert metadata["total_bytes"] == 11  # "hello world"
        assert "sample.txt" in metadata["extracted_files"]
        assert (extract_dir / "sample.txt").exists()


class TestReceiverLandingZoneDiscovery:
    """Tests for list_sender_agencies() and list_pending_transfers() methods."""

    def test_list_sender_agencies_returns_all_folders(self, receiver_landing_zone):
        """Returns all top-level agency folder names from the landing bucket."""
        receiver_landing_zone.s3_client._client.list_objects_v2.return_value = {
            "CommonPrefixes": [
                {"Prefix": "dot/"},
                {"Prefix": "hud/"},
                {"Prefix": "faa/"},
            ]
        }

        agencies = receiver_landing_zone.list_sender_agencies()

        assert agencies == ["dot", "hud", "faa"]
        receiver_landing_zone.s3_client._client.list_objects_v2.assert_called_once_with(
            Bucket="gsa-data-dev-landing",
            Delimiter="/",
        )

    def test_list_sender_agencies_empty_bucket(self, receiver_landing_zone):
        """Returns empty list when no sender folders exist yet."""
        receiver_landing_zone.s3_client._client.list_objects_v2.return_value = {}

        agencies = receiver_landing_zone.list_sender_agencies()

        assert agencies == []

    def test_list_sender_agencies_s3_failure_raises_storage_error(self, receiver_landing_zone):
        """Wraps S3 errors in StorageError."""
        receiver_landing_zone.s3_client._client.list_objects_v2.side_effect = Exception("Access Denied")

        with pytest.raises(StorageError, match="Failed to list sender agencies"):
            receiver_landing_zone.list_sender_agencies()

    def test_list_pending_transfers_returns_session_ids(self, receiver_landing_zone):
        """Returns transfer session IDs from the sender's transfers/ subfolder."""
        receiver_landing_zone.s3_client._client.list_objects_v2.return_value = {
            "CommonPrefixes": [
                {"Prefix": "dot/transfers/sess-001/"},
                {"Prefix": "dot/transfers/sess-002/"},
            ]
        }

        sessions = receiver_landing_zone.list_pending_transfers("dot")

        assert sessions == ["sess-001", "sess-002"]
        receiver_landing_zone.s3_client._client.list_objects_v2.assert_called_once_with(
            Bucket="gsa-data-dev-landing",
            Delimiter="/",
            Prefix="dot/transfers/",
        )

    def test_list_pending_transfers_no_sessions(self, receiver_landing_zone):
        """Returns empty list when sender has no transfer sessions."""
        receiver_landing_zone.s3_client._client.list_objects_v2.return_value = {}

        sessions = receiver_landing_zone.list_pending_transfers("dot")

        assert sessions == []

    def test_list_pending_transfers_s3_failure_raises_storage_error(self, receiver_landing_zone):
        """Wraps S3 errors in StorageError."""
        receiver_landing_zone.s3_client._client.list_objects_v2.side_effect = Exception("Timeout")

        with pytest.raises(StorageError, match="Failed to list pending transfers"):
            receiver_landing_zone.list_pending_transfers("dot")

    def test_decompress_creates_target_directory(self, receiver_landing_zone, sample_archive, tmp_path):
        """Test decompression creates target directory if it doesn't exist."""
        extract_dir = tmp_path / "nonexistent" / "extract"

        metadata = receiver_landing_zone.decompress_archive(
            archive_bytes=sample_archive,
            target_directory=extract_dir,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert extract_dir.exists()
        assert metadata["file_count"] == 1

    def test_decompress_invalid_archive(self, receiver_landing_zone):
        """Test decompression fails with invalid tar.gz data."""
        invalid_archive = b"not a valid tar.gz"

        with pytest.raises(StorageError, match="Failed to decompress"):
            receiver_landing_zone.decompress_archive(
                archive_bytes=invalid_archive,
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )

    def test_decompress_without_audit_logging(self, receiver_landing_zone, sample_archive, tmp_path):
        """Test decompression works without audit logging params."""
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        metadata = receiver_landing_zone.decompress_archive(
            archive_bytes=sample_archive,
            target_directory=extract_dir,
        )

        assert metadata["file_count"] == 1

    def test_decompress_multiple_files(self, receiver_landing_zone, tmp_path):
        """Test decompression of archive with multiple files."""
        # Create archive with multiple files
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            for i in range(3):
                info = tarfile.TarInfo(name=f"file{i}.txt")
                content = f"content{i}".encode()
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        archive_bytes = tar_buffer.getvalue()

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        metadata = receiver_landing_zone.decompress_archive(
            archive_bytes=archive_bytes,
            target_directory=extract_dir,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        assert metadata["file_count"] == 3
        assert all((extract_dir / f"file{i}.txt").exists() for i in range(3))

    def test_decompress_path_traversal_protection(self, receiver_landing_zone, tmp_path):
        """Test decompression rejects path traversal attempts."""
        # Create archive with path traversal attempt
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../evil.txt")
            content = b"malicious"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        archive_bytes = tar_buffer.getvalue()

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        with pytest.raises(StorageError, match="path traversal"):
            receiver_landing_zone.decompress_archive(
                archive_bytes=archive_bytes,
                target_directory=extract_dir,
                transfer_session_id="transfer-20260406-001",
                sender_agency="dot",
                receiver_agency="gsa",
            )


class TestReceiverLandingZoneIntegration:
    """Integration tests for complete landing zone workflow."""

    def test_complete_landing_workflow(
        self, receiver_landing_zone, sample_archive, sample_manifest, tmp_path
    ):
        """Test complete workflow: fetch -> validate -> decompress."""
        # Mock S3 responses
        manifest_bytes = json.dumps(sample_manifest).encode("utf-8")
        
        manifest_response = {"Body": mock.MagicMock()}
        manifest_response["Body"].read.return_value = manifest_bytes
        
        archive_response = {"Body": mock.MagicMock()}
        archive_response["Body"].read.return_value = sample_archive
        
        def get_object_side_effect(**kwargs):
            if "manifest.json" in kwargs["Key"]:
                return manifest_response
            elif "transfer.tar.gz" in kwargs["Key"]:
                return archive_response
            raise ValueError(f"Unexpected key: {kwargs['Key']}")
        
        receiver_landing_zone.s3_client._client.get_object.side_effect = get_object_side_effect

        # Step 1: Fetch
        archive_bytes, manifest_dict = receiver_landing_zone.fetch_from_landing_bucket(
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Step 2: Validate
        manifest = receiver_landing_zone.validate_manifest(
            manifest_dict=manifest_dict,
            archive_bytes=archive_bytes,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Step 3: Decompress
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        metadata = receiver_landing_zone.decompress_archive(
            archive_bytes=archive_bytes,
            target_directory=extract_dir,
            transfer_session_id="transfer-20260406-001",
            sender_agency="dot",
            receiver_agency="gsa",
        )

        # Verify complete workflow
        assert manifest.transfer_session_id == "transfer-20260406-001"
        assert metadata["file_count"] == 1
        assert (extract_dir / "sample.txt").exists()
