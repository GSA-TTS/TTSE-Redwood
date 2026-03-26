"""Unit tests for Day 1 manifest data models.

These tests focus on the receiver contract guarantees for Day 1:
- strict checksum shape validation
- non-blank required identifiers
- file-count integrity between top-level and file entries
- stable JSON-ready serialization for downstream logging/transport
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from redwood_dataagent.models import (
    ChecksumAlgorithm,
    CompressionType,
    ManifestFile,
    TransferManifest,
)


def _sha256(value: str = "a") -> str:
    """Return a deterministic 64-char hex string for tests."""
    return value * 64


class TestManifestFile:
    """Validation tests for file-level manifest metadata."""

    def test_valid_manifest_file(self):
        """Accept a valid file entry with required fields and default role."""
        item = ManifestFile(
            file_name="data.tar.gz",
            file_size_bytes=1024,
            checksum_sha256=_sha256("a"),
        )

        assert item.file_name == "data.tar.gz"
        assert item.file_size_bytes == 1024
        assert item.checksum_sha256 == _sha256("a")

    def test_reject_blank_file_name(self):
        """Reject file names that are only whitespace."""
        with pytest.raises(ValidationError):
            ManifestFile(
                file_name="   ",
                file_size_bytes=1,
                checksum_sha256=_sha256("a"),
            )

    def test_reject_invalid_checksum(self):
        """Reject checksum values containing non-hex characters."""
        with pytest.raises(ValidationError):
            ManifestFile(
                file_name="data.tar.gz",
                file_size_bytes=1,
                checksum_sha256="z" * 64,
            )

    def test_reject_short_checksum(self):
        """Reject checksum values that are not the full 64-char SHA-256 size."""
        with pytest.raises(ValidationError):
            ManifestFile(
                file_name="data.tar.gz",
                file_size_bytes=1,
                checksum_sha256="abc123",
            )


class TestTransferManifest:
    """Validation and serialization tests for top-level Day 1 manifest."""

    def test_valid_manifest_creation(self):
        """Accept a valid Day 1 manifest and verify key defaults."""
        manifest = TransferManifest(
            transfer_session_id="transfer-20260325-001",
            sender_agency="dot",
            receiver_agency="gsa",
            total_file_count=1,
            files=[
                ManifestFile(
                    file_name="data.tar.gz",
                    file_size_bytes=2048,
                    checksum_sha256=_sha256("b"),
                )
            ],
        )

        assert manifest.manifest_version == "1.0"
        assert manifest.checksum_algorithm == ChecksumAlgorithm.SHA256
        assert manifest.compression_type == CompressionType.GZIP
        assert manifest.total_file_count == 1
        assert len(manifest.files) == 1
        assert manifest.created_at.tzinfo is not None

    def test_timestamp_defaults_to_now(self):
        """Set created_at automatically to current UTC time when omitted."""
        before = datetime.now(timezone.utc)
        manifest = TransferManifest(
            transfer_session_id="transfer-20260325-001",
            sender_agency="dot",
            receiver_agency="gsa",
            total_file_count=1,
            files=[
                ManifestFile(
                    file_name="data.tar.gz",
                    file_size_bytes=1,
                    checksum_sha256=_sha256("c"),
                )
            ],
        )
        after = datetime.now(timezone.utc)

        assert before <= manifest.created_at <= after

    def test_reject_blank_required_text_fields(self):
        """Reject required identifiers that are blank after trimming."""
        with pytest.raises(ValidationError):
            TransferManifest(
                transfer_session_id="   ",
                sender_agency="dot",
                receiver_agency="gsa",
                total_file_count=1,
                files=[
                    ManifestFile(
                        file_name="data.tar.gz",
                        file_size_bytes=1,
                        checksum_sha256=_sha256("d"),
                    )
                ],
            )

    def test_reject_file_count_mismatch(self):
        """Reject manifests where total_file_count does not match files length."""
        with pytest.raises(ValidationError):
            TransferManifest(
                transfer_session_id="transfer-1",
                sender_agency="dot",
                receiver_agency="gsa",
                total_file_count=2,
                files=[
                    ManifestFile(
                        file_name="data.tar.gz",
                        file_size_bytes=1,
                        checksum_sha256=_sha256("f"),
                    )
                ],
            )

    def test_reject_empty_files_collection(self):
        """Reject manifests that include no file entries."""
        with pytest.raises(ValidationError):
            TransferManifest(
                transfer_session_id="transfer-1",
                sender_agency="dot",
                receiver_agency="gsa",
                total_file_count=1,
                files=[],
            )

    def test_structured_dict_serialization(self):
        """Serialize manifest with enum values normalized to JSON primitives."""
        manifest = TransferManifest(
            transfer_session_id="transfer-20260325-009",
            sender_agency="dot",
            receiver_agency="gsa",
            total_file_count=1,
            files=[
                ManifestFile(
                    file_name="data.tar.gz",
                    file_size_bytes=2048,
                    checksum_sha256=_sha256("0"),
                )
            ],
        )

        payload = manifest.to_structured_dict()
        assert payload["checksum_algorithm"] == "sha256"
        assert payload["compression_type"] == "gzip"
        assert payload["transfer_session_id"] == "transfer-20260325-009"
        assert payload["files"][0]["checksum_sha256"] == _sha256("0")
        assert "created_at" in payload
