"""Receiver landing zone ingest for TTSE Redwood Data Agent.

This module handles receiver-side data ingest from S3 landing zone:
- Fetch transfer artifacts (archive + manifest) from S3 landing
- Validate manifest integrity and checksum verification
- Decompress archive to working directory
- Emit audit events for ingest workflow
"""

import hashlib
import io
import json
import logging
import tarfile
import tempfile
from pathlib import Path

from redwood_dataagent.audit.events import AuditEventType, EventOutcome
from redwood_dataagent.audit.logger import log_event
from redwood_dataagent.aws.s3 import S3Client
from redwood_dataagent.exceptions import ManifestValidationError, StorageError
from redwood_dataagent.models.manifest import (
    TransferManifest,
    normalize_archive_fields_to_standard,
)
from redwood_dataagent.storage.conventions import ReceiverStoragePath

_logger = logging.getLogger(__name__)

_STREAM_CHUNK_SIZE = 8 * 1024 * 1024
_ARCHIVE_FILENAME = "transfer.tar.gz"


class ReceiverLandingZone:
    """Receiver agent for landing zone ingest and validation.

    This class orchestrates the receiver-side data flow:
    1. Fetch archive and manifest from S3 landing zone
    2. Validate manifest and verify checksums
    3. Decompress archive to working directory

    Attributes:
        s3_client: S3Client for reading landing zone artifacts
        landing_bucket: S3 bucket name for landing zone
        environment: Deployment environment (dev/staging/prod)
    """

    def __init__(
        self,
        s3_client: S3Client,
        landing_bucket: str,
        environment: str,
    ):
        """Initialize ReceiverLandingZone.

        Args:
            s3_client: S3Client instance for storage operations
            landing_bucket: S3 bucket name for landing zone (e.g., gsa-data-dev-landing)
            environment: Deployment environment (dev/staging/prod)
        """
        self.s3_client = s3_client
        self.landing_bucket = landing_bucket
        self.environment = environment

    def list_sender_agencies(self) -> list[str]:
        """List all sender agency folders currently present in the landing bucket.

        Scans top-level S3 common prefixes to discover which sender agencies
        have delivered files.

        Returns:
            List of sender agency codes (e.g., ["dot", "hud", "faa"])

        Raises:
            StorageError: If the S3 listing fails
        """
        try:
            response = self.s3_client._client.list_objects_v2(
                Bucket=self.landing_bucket,
                Delimiter="/",
            )
            prefixes = response.get("CommonPrefixes", [])
            agencies = [p["Prefix"].rstrip("/") for p in prefixes]
            _logger.debug(f"Found {len(agencies)} sender agency folder(s) in landing bucket: {agencies}")
            return agencies
        except Exception as e:
            raise StorageError(f"Failed to list sender agencies in {self.landing_bucket}: {e}") from e

    def list_pending_transfers(self, sender_agency: str) -> list[str]:
        """List transfer session IDs under a sender agency folder.

        Scans ``{sender_agency}/`` for session sub-folders.
        The target-store idempotency marker prevents re-processing already-stored sessions.

        Args:
            sender_agency: Sender agency code (e.g., "dot")

        Returns:
            List of transfer session IDs (e.g., ["sess-001", "sess-002"])

        Raises:
            StorageError: If the S3 listing fails
        """
        try:
            prefix = f"{sender_agency}/"
            response = self.s3_client._client.list_objects_v2(
                Bucket=self.landing_bucket,
                Delimiter="/",
                Prefix=prefix,
            )
            prefixes = response.get("CommonPrefixes", [])
            # "dot/sess-001/" → "sess-001"
            sessions = [p["Prefix"].rstrip("/").split("/")[-1] for p in prefixes]
            _logger.debug(f"Found {len(sessions)} transfer session(s) for sender {sender_agency}: {sessions}")
            return sessions
        except Exception as e:
            raise StorageError(f"Failed to list pending transfers for sender {sender_agency}: {e}") from e

    def fetch_from_landing_bucket(
        self,
        transfer_session_id: str,
        sender_agency: str,
        receiver_agency: str,
        target_directory: Path | None = None,
    ) -> tuple[Path | bytes, dict]:
        """Download archive and manifest from S3 landing zone.

        Args:
            transfer_session_id: Unique transfer correlation ID
            sender_agency: Sending agency code
            receiver_agency: Receiving agency code
                target_directory: Optional directory for streaming archive download.
                    If provided, archive is streamed to disk and returned as ``Path``.
                    If omitted, archive is returned as bytes for backward compatibility.

        Returns:
            Tuple of (archive_path_or_bytes, manifest_dict)

        Raises:
            StorageError: If S3 download fails
        """
        try:
            # Construct S3 paths scoped by sender agency prefix.
            manifest_key = ReceiverStoragePath.landing(
                transfer_session_id,
                "manifest.json",
                sender_agency,
            )
            archive_key = ReceiverStoragePath.landing(
                transfer_session_id,
                _ARCHIVE_FILENAME,
                sender_agency,
            )

            # Download manifest first to validate before downloading large archive
            manifest_bytes = self._download_from_s3(manifest_key, "manifest.json")
            manifest_dict = json.loads(manifest_bytes.decode("utf-8"))

            if target_directory is not None:
                target_directory.mkdir(parents=True, exist_ok=True)
                archive_path = target_directory / _ARCHIVE_FILENAME
                archive_size = self._download_to_file(archive_key, _ARCHIVE_FILENAME, archive_path)
                archive_payload: Path | bytes = archive_path
            else:
                archive_bytes = self._download_from_s3(archive_key, _ARCHIVE_FILENAME)
                archive_size = len(archive_bytes)
                archive_payload = archive_bytes

            # Log successful receiver fetch from landing storage.
            log_event(
                event_type=AuditEventType.EXTRACT_DATA,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.SUCCESS,
                bytes_transferred=archive_size,
                details={
                    "action": "landing_fetch_complete",
                    "archive_size_bytes": archive_size,
                    "manifest_size_bytes": len(manifest_bytes),
                },
            )

            return archive_payload, manifest_dict

        except StorageError:
            raise
        except Exception as e:
            error_msg = f"Failed to fetch from landing bucket: {str(e)}"
            _logger.error(error_msg)

            # Log failed fetch
            log_event(
                event_type=AuditEventType.EXTRACT_DATA,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.FAILURE,
                details={"action": "landing_fetch_failed", "error": str(e)},
            )

            raise StorageError(error_msg) from e

    def validate_manifest(
        self,
        manifest_dict: dict,
        transfer_session_id: str,
        sender_agency: str,
        receiver_agency: str,
        archive_bytes: bytes | None = None,
        archive_path: Path | None = None,
    ) -> TransferManifest:
        """Validate manifest and verify archive checksum.

        Args:
            manifest_dict: Parsed manifest JSON
            archive_bytes: Archive file content in memory (legacy compatibility)
            archive_path: Archive file path on disk (preferred for large files)
            transfer_session_id: Transfer correlation ID
            sender_agency: Sending agency code
            receiver_agency: Receiving agency code

        Returns:
            Validated TransferManifest instance

        Raises:
            ManifestValidationError: If manifest is invalid or checksum mismatches
        """
        try:
            # Normalize archive fields from zip_* names back to standard names
            # before model validation
            manifest_dict_normalized = normalize_archive_fields_to_standard(manifest_dict)

            # Parse and validate manifest structure
            manifest = TransferManifest(**manifest_dict_normalized)

            if archive_path is not None:
                archive_checksum = self._compute_sha256_for_file(archive_path)
            elif archive_bytes is not None:
                archive_checksum = hashlib.sha256(archive_bytes).hexdigest()
            else:
                raise ManifestValidationError("Either archive_path or archive_bytes must be provided")

            # Manifest should have 2 entries: source file + archive
            # First entry: original source file (file_name, file_size_bytes, checksum_sha256)
            # Second entry: compressed archive (file_name, file_size_bytes, checksum_sha256)
            if len(manifest.files) != 2:
                raise ManifestValidationError(
                    f"Expected 2 file entries in manifest (source + archive), got {len(manifest.files)}"
                )

            # Archive is the second entry - use its checksum for validation
            archive_entry = manifest.files[1]
            expected_checksum = archive_entry.checksum_sha256

            if archive_checksum != expected_checksum:
                error_msg = f"Archive checksum mismatch: " f"expected {expected_checksum}, got {archive_checksum}"
                raise ManifestValidationError(error_msg)

            # Log successful validation
            log_event(
                event_type=AuditEventType.VALIDATE_MANIFEST,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.SUCCESS,
                details={
                    "action": "manifest_validation_success",
                    "checksum_algorithm": manifest.checksum_algorithm.value,
                    "archive_checksum": archive_checksum,
                },
            )

            return manifest

        except ManifestValidationError:
            raise
        except Exception as e:
            error_msg = f"Manifest validation failed: {str(e)}"
            _logger.error(error_msg)

            # Log failed validation
            log_event(
                event_type=AuditEventType.VALIDATE_MANIFEST,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.FAILURE,
                details={"action": "manifest_validation_failed", "error": str(e)},
            )

            raise ManifestValidationError(error_msg) from e

    def decompress_archive(
        self,
        target_directory: Path | None = None,
        transfer_session_id: str | None = None,
        sender_agency: str | None = None,
        receiver_agency: str | None = None,
        archive_bytes: bytes | None = None,
        archive_path: Path | None = None,
    ) -> dict:
        """Decompress tar.gz archive to working directory.

        Args:
            archive_bytes: Archive file content in bytes (legacy compatibility)
            archive_path: Archive file path on disk (preferred for large files)
            target_directory: Directory to extract to. If None, use temp directory.
            transfer_session_id: Transfer correlation ID (for audit logging)
            sender_agency: Sending agency code (for audit logging)
            receiver_agency: Receiving agency code (for audit logging)

        Returns:
            Dictionary with extraction metadata:
            - file_count: Number of files extracted
            - total_bytes: Total bytes extracted
            - extracted_files: List of extracted file paths

        Raises:
            StorageError: If decompression fails or archive is invalid
        """
        try:
            extract_dir = self._prepare_extract_directory(target_directory)
            tar_context = self._open_archive(archive_path=archive_path, archive_bytes=archive_bytes)

            with tar_context as tar:
                extracted_files, total_bytes = self._extract_archive_members(
                    tar=tar,
                    target_directory=extract_dir,
                )

            extraction_metadata = {
                "file_count": len(extracted_files),
                "total_bytes": total_bytes,
                "extracted_files": extracted_files,
                "target_directory": str(extract_dir),
            }

            # Log successful decompression
            if transfer_session_id and sender_agency and receiver_agency:
                log_event(
                    event_type=AuditEventType.DECOMPRESS,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=receiver_agency,
                    stage="receiver",
                    outcome=EventOutcome.SUCCESS,
                    details={
                        "action": "decompress_success",
                        "file_count": len(extracted_files),
                        "total_bytes": total_bytes,
                    },
                )

            return extraction_metadata

        except Exception as e:
            error_msg = f"Failed to decompress archive: {str(e)}"
            _logger.error(error_msg)

            # Log failed decompression
            if transfer_session_id and sender_agency and receiver_agency:
                log_event(
                    event_type=AuditEventType.DECOMPRESS,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=receiver_agency,
                    stage="receiver",
                    outcome=EventOutcome.FAILURE,
                    details={"action": "decompress_failed", "error": str(e)},
                )

            raise StorageError(error_msg) from e

    def _prepare_extract_directory(self, target_directory: Path | None) -> Path:
        """Prepare and return extraction target directory."""
        if target_directory is None:
            # Create secure temp directory with restricted permissions (0o700)
            temp_dir = tempfile.mkdtemp(prefix="redwood-receiver-extract-")
            return Path(temp_dir)

        target_directory.mkdir(parents=True, exist_ok=True)
        return target_directory

    def _open_archive(
        self,
        archive_path: Path | None,
        archive_bytes: bytes | None,
    ) -> tarfile.TarFile:
        """Open tar.gz archive from path or bytes."""
        if archive_path is not None:
            return tarfile.open(name=str(archive_path), mode="r:gz")  # NOSONAR
        if archive_bytes is None:
            raise StorageError("Either archive_path or archive_bytes must be provided")
        return tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")  # NOSONAR

    def _extract_archive_members(
        self,
        tar: tarfile.TarFile,
        target_directory: Path,
    ) -> tuple[list[str], int]:
        """Extract regular files from archive and return extracted names and byte count."""
        extracted_files: list[str] = []
        total_bytes = 0
        target_root = target_directory.resolve()

        for member in tar.getmembers():
            if not member.isfile():
                continue

            self._validate_archive_member_path(member.name, target_root)
            extracted_path = target_directory / member.name
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            tar.extract(member, path=target_directory)
            extracted_files.append(member.name)
            total_bytes += member.size

        return extracted_files, total_bytes

    def _validate_archive_member_path(self, member_name: str, target_root: Path) -> None:
        """Validate archive member path does not escape target directory."""
        extracted_path = (target_root / member_name).resolve()
        try:
            extracted_path.relative_to(target_root)
        except ValueError as exc:
            raise StorageError(f"Archive contains path traversal: {member_name}") from exc

    def _download_from_s3(self, s3_key: str, file_type: str) -> bytes:
        """Helper to download file from S3 landing bucket.

        Args:
            s3_key: S3 object key path
            file_type: Description of file (for logging)

        Returns:
            File content as bytes

        Raises:
            StorageError: If download fails
        """
        try:
            # Use S3Client to download file
            file_content = io.BytesIO()

            # Download from S3
            response = self.s3_client._client.get_object(Bucket=self.landing_bucket, Key=s3_key)
            file_content.write(response["Body"].read())

            return file_content.getvalue()

        except Exception as e:
            error_msg = f"Failed to download {file_type} from s3://{self.landing_bucket}/{s3_key}: {str(e)}"
            _logger.error(error_msg)
            raise StorageError(error_msg) from e

    def _download_to_file(self, s3_key: str, file_type: str, destination_path: Path) -> int:
        """Stream an S3 object directly to disk and return bytes written."""
        try:
            response = self.s3_client._client.get_object(
                Bucket=self.landing_bucket,
                Key=s3_key,
            )
            body = response["Body"]
            bytes_written = 0

            with destination_path.open("wb") as destination:
                while True:
                    chunk = body.read(_STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    destination.write(chunk)
                    bytes_written += len(chunk)

            return bytes_written
        except Exception as e:
            error_msg = f"Failed to download {file_type} from s3://{self.landing_bucket}/{s3_key}: {str(e)}"
            _logger.error(error_msg)
            raise StorageError(error_msg) from e

    def _compute_sha256_for_file(self, file_path: Path) -> str:
        """Compute SHA256 hash for a file using streaming chunks."""
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
