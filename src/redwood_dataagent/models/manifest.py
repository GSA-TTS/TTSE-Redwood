"""
Day 1 manifest data models for TTSE Redwood Data Agent.

The Day 1 MVP transfer contract is manifest-centric. These models define the
sender-generated metadata that the receiver uses as the source of truth for
integrity validation before decompression and target storage.
"""

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChecksumAlgorithm(str, Enum):
    """Supported checksum algorithms for Day 1 validation."""

    SHA256 = "sha256"


class CompressionType(str, Enum):
    """Supported payload compression formats for Day 1 transfers."""

    GZIP = "gzip"


class ManifestFile(BaseModel):
    """File-level metadata entry used by receiver-side integrity checks."""

    file_name: str = Field(..., min_length=1, description="Transferred file name")
    file_size_bytes: int = Field(
        ..., ge=0, description="Transferred file size in bytes"
    )
    checksum_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="64-character SHA-256 hex digest",
    )
    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        """Disallow blank file names after trimming whitespace."""
        if not value.strip():
            raise ValueError("file_name cannot be blank")
        return value

    @field_validator("checksum_sha256")
    @classmethod
    def validate_checksum_sha256(cls, value: str) -> str:
        """Require lowercase or uppercase hex digest with exact SHA-256 length."""
        if not all(char in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("checksum_sha256 must be a valid hex digest")
        return value.lower()


class TransferManifest(BaseModel):
    """Top-level Day 1 manifest used as the receiver validation contract.

    The receiver treats this manifest as the source of truth before any
    decompression or storage write. The ``total_file_count`` and ``files``
    collection must stay in sync, and all file checksums must be SHA-256.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "manifest_version": "1.0",
                "transfer_session_id": "transfer-20260325-001",
                "sender_agency": "dot",
                "receiver_agency": "gsa",
                "created_at": "2026-03-25T13:45:00Z",
                "checksum_algorithm": "sha256",
                "total_file_count": 1,
                "compression_type": "gzip",
                "transfer_date": "2026-03-25",
                "files": [
                    {
                        "file_name": "data.tar.gz",
                        "file_size_bytes": 1048576,
                        "checksum_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    }
                ],
            }
        }
    )

    manifest_version: str = Field(
        default="1.0", min_length=1, description="Manifest schema version"
    )
    transfer_session_id: str = Field(
        ..., min_length=1, description="Correlation ID for one transfer session"
    )
    sender_agency: str = Field(..., min_length=1, description="Sender agency code")
    receiver_agency: str = Field(
        default="", description="Receiver agency code"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the manifest was generated",
    )
    checksum_algorithm: ChecksumAlgorithm = Field(
        default=ChecksumAlgorithm.SHA256,
        description="Checksum algorithm used for all file entries",
    )
    total_file_count: int = Field(
        ..., ge=1, description="Declared number of files in the manifest"
    )
    files: list[ManifestFile] = Field(
        ..., min_length=1, description="Per-file metadata entries"
    )

    compression_type: CompressionType = Field(
        default=CompressionType.GZIP,
        description="Compression format for payload artifacts",
    )
    transfer_date: date | None = Field(
        default=None, description="Optional transfer date for operational tracing"
    )
    business_date: date | None = Field(
        default=None,
        description="Optional business-effective date for downstream consumers",
    )

    @field_validator(
        "transfer_session_id",
        "sender_agency",
        "manifest_version",
    )
    @classmethod
    def validate_required_text_fields(cls, value: str) -> str:
        """Disallow values that are only whitespace for required text fields."""
        if not value.strip():
            raise ValueError("field cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_file_count_matches_files(self) -> "TransferManifest":
        """Ensure top-level total_file_count matches actual listed files."""
        if self.total_file_count != len(self.files):
            raise ValueError("total_file_count must equal number of files entries")
        return self

    def to_structured_dict(self) -> dict:
        """Return a JSON-ready dictionary for logging or transport boundaries."""
        return self.model_dump(mode="json")
