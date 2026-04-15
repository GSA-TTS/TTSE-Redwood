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
from typing import Optional

from redwood_dataagent.audit.events import AuditEventType, EventOutcome
from redwood_dataagent.audit.logger import log_event
from redwood_dataagent.exceptions import ManifestValidationError, StorageError
from redwood_dataagent.models.manifest import TransferManifest
from redwood_dataagent.storage.conventions import ReceiverStoragePath
from redwood_dataagent.aws.s3 import S3Client

_logger = logging.getLogger(__name__)


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
            _logger.info(
                f"Found {len(agencies)} sender agency folder(s) in landing bucket: {agencies}"
            )
            return agencies
        except Exception as e:
            raise StorageError(
                f"Failed to list sender agencies in {self.landing_bucket}: {e}"
            ) from e

    def list_pending_transfers(self, sender_agency: str) -> list[str]:
        """List transfer session IDs under a sender agency folder.

        Scans ``{sender_agency}/transfers/`` for session sub-folders.
        The target-store idempotency marker prevents re-processing already-stored sessions.

        Args:
            sender_agency: Sender agency code (e.g., "dot")

        Returns:
            List of transfer session IDs (e.g., ["sess-001", "sess-002"])

        Raises:
            StorageError: If the S3 listing fails
        """
        try:
            prefix = f"{sender_agency}/transfers/"
            response = self.s3_client._client.list_objects_v2(
                Bucket=self.landing_bucket,
                Delimiter="/",
                Prefix=prefix,
            )
            prefixes = response.get("CommonPrefixes", [])
            # "dot/transfers/sess-001/" → "sess-001"
            sessions = [p["Prefix"].rstrip("/").split("/")[-1] for p in prefixes]
            _logger.info(
                f"Found {len(sessions)} transfer session(s) for sender {sender_agency}: {sessions}"
            )
            return sessions
        except Exception as e:
            raise StorageError(
                f"Failed to list pending transfers for sender {sender_agency}: {e}"
            ) from e

    def fetch_from_landing_bucket(
        self,
        transfer_session_id: str,
        sender_agency: str,
        receiver_agency: str,
    ) -> tuple[bytes, dict]:
        """Download archive and manifest from S3 landing zone.

        Args:
            transfer_session_id: Unique transfer correlation ID
            sender_agency: Sending agency code
            receiver_agency: Receiving agency code

        Returns:
            Tuple of (archive_bytes, manifest_dict)

        Raises:
            StorageError: If S3 download fails
        """
        try:
            # Log fetch attempt
            log_event(
                event_type=AuditEventType.SFTP_TRANSFER_START,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.SUCCESS,
                details={
                    "action": "landing_fetch_start",
                    "bucket": self.landing_bucket,
                    "transfer_session_id": transfer_session_id,
                },
            )

            # Construct S3 paths scoped by sender agency prefix.
            manifest_key = ReceiverStoragePath.landing(
                transfer_session_id,
                "manifest.json",
                sender_agency,
            )
            archive_key = ReceiverStoragePath.landing(
                transfer_session_id,
                "transfer.tar.gz",
                sender_agency,
            )

            # Download manifest first to validate before downloading large archive
            manifest_bytes = self._download_from_s3(manifest_key, "manifest.json")
            manifest_dict = json.loads(manifest_bytes.decode("utf-8"))

            # Download archive
            archive_bytes = self._download_from_s3(archive_key, "transfer.tar.gz")

            # Log successful fetch
            log_event(
                event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.SUCCESS,
                bytes_transferred=len(archive_bytes),
                details={
                    "action": "landing_fetch_complete",
                    "archive_size_bytes": len(archive_bytes),
                    "manifest_size_bytes": len(manifest_bytes),
                },
            )

            return archive_bytes, manifest_dict

        except StorageError:
            raise
        except Exception as e:
            error_msg = f"Failed to fetch from landing bucket: {str(e)}"
            _logger.error(error_msg)

            # Log failed fetch
            log_event(
                event_type=AuditEventType.SFTP_TRANSFER_COMPLETE,
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
        archive_bytes: bytes,
        transfer_session_id: str,
        sender_agency: str,
        receiver_agency: str,
    ) -> TransferManifest:
        """Validate manifest and verify archive checksum.

        Args:
            manifest_dict: Parsed manifest JSON
            archive_bytes: Archive file content
            transfer_session_id: Transfer correlation ID
            sender_agency: Sending agency code
            receiver_agency: Receiving agency code

        Returns:
            Validated TransferManifest instance

        Raises:
            ManifestValidationError: If manifest is invalid or checksum mismatches
        """
        try:
            # Parse and validate manifest structure
            manifest = TransferManifest(**manifest_dict)

            # Verify archive checksum against manifest
            archive_checksum = hashlib.sha256(archive_bytes).hexdigest()

            # Manifest should have one entry for the archive
            if len(manifest.files) != 1:
                raise ManifestValidationError(
                    f"Expected 1 file entry in manifest, got {len(manifest.files)}"
                )

            expected_checksum = manifest.files[0].checksum_sha256
            if archive_checksum != expected_checksum:
                error_msg = (
                    f"Archive checksum mismatch: "
                    f"expected {expected_checksum}, got {archive_checksum}"
                )
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
        archive_bytes: bytes,
        target_directory: Optional[Path] = None,
        transfer_session_id: Optional[str] = None,
        sender_agency: Optional[str] = None,
        receiver_agency: Optional[str] = None,
    ) -> dict:
        """Decompress tar.gz archive to working directory.

        Args:
            archive_bytes: Archive file content in bytes
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
            if target_directory is None:
                # Create secure temp directory with restricted permissions (0o700)
                temp_dir = tempfile.mkdtemp(prefix="redwood-receiver-extract-")
                target_directory = Path(temp_dir)
            else:
                target_directory.mkdir(parents=True, exist_ok=True)

            # Extract tar.gz
            extracted_files = []
            total_bytes = 0

            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:  # NOSONAR
                for member in tar.getmembers():
                    if member.isfile():
                        extracted_path = target_directory / member.name
                        
                        # Prevent path traversal: ensure extracted file stays within target_directory
                        try:
                            extracted_path.resolve().relative_to(target_directory.resolve())
                        except ValueError:
                            raise StorageError(f"Archive contains path traversal: {member.name}")
                        
                        extracted_path.parent.mkdir(parents=True, exist_ok=True)
                        tar.extractall(
                            path=target_directory,
                            members=[member],
                            filter="data"  # Security: only extract regular files, skip symbolic links
                        )
                        extracted_files.append(member.name)
                        total_bytes += member.size

            extraction_metadata = {
                "file_count": len(extracted_files),
                "total_bytes": total_bytes,
                "extracted_files": extracted_files,
                "target_directory": str(target_directory),
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
            response = self.s3_client._client.get_object(
                Bucket=self.landing_bucket,
                Key=s3_key
            )
            file_content.write(response['Body'].read())
            
            return file_content.getvalue()

        except Exception as e:
            error_msg = f"Failed to download {file_type} from s3://{self.landing_bucket}/{s3_key}: {str(e)}"
            _logger.error(error_msg)
            raise StorageError(error_msg) from e
