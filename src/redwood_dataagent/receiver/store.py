"""Receiver target store for TTSE Redwood Data Agent.

This module handles receiver-side storage of decompressed data to target S3 bucket:
- Persist extracted payload to target S3 bucket
- Implement idempotency guard via S3 marker objects
- Emit audit events for store workflow
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from redwood_dataagent.audit.events import AuditEventType, EventOutcome
from redwood_dataagent.audit.logger import log_event
from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.aws.s3 import S3Client

_logger = logging.getLogger(__name__)


class ReceiverTargetStore:
    """Receiver agent for target store operations.

    This class orchestrates the receiver target storage:
    1. Check idempotency (marker object for transfer_session_id)
    2. Upload extracted files to target S3 bucket
    3. Create marker object to prevent duplicate writes
    4. Emit audit events for store workflow

    Attributes:
        s3_client: S3Client for storage operations
        target_bucket: S3 bucket name for target store
        environment: Deployment environment (dev/staging/prod)
    """

    def __init__(
        self,
        s3_client: S3Client,
        target_bucket: str,
        environment: str,
    ):
        """Initialize ReceiverTargetStore.

        Args:
            s3_client: S3Client instance for storage operations
            target_bucket: S3 bucket name for target store (e.g., tts-core-dev-gsa-data-target)
            environment: Deployment environment (dev/staging/prod)
        """
        self.s3_client = s3_client
        self.target_bucket = target_bucket
        self.environment = environment

    def store_to_target(
        self,
        extracted_files_dir: Path,
        transfer_session_id: str,
        sender_agency: str,
        receiver_agency: str,
    ) -> dict:
        """Store extracted files to target S3 bucket with idempotency.

        Uses S3 marker object (processed/{sender_agency}/{transfer_session_id}.done) to prevent
        duplicate uploads on retry.

        Args:
            extracted_files_dir: Directory containing extracted files
            transfer_session_id: Unique transfer correlation ID
            sender_agency: Sending agency code
            receiver_agency: Receiving agency code

        Returns:
            Dictionary with store metadata:
            - status: "stored" | "already_stored"
            - file_count: Number of files stored
            - total_bytes: Total bytes stored
            - target_location: S3 target prefix
            - stored_at: ISO timestamp of store operation

        Raises:
            StorageError: If store operation fails
        """
        try:
            marker_key = f"processed/{sender_agency}/{transfer_session_id}.done"
            target_location = f"s3://{self.target_bucket}/transfers/{sender_agency}/{transfer_session_id}/"

            # Step 1: Check idempotency (marker object)
            if self._is_already_stored(marker_key):
                _logger.info(f"Transfer {transfer_session_id} already stored (idempotency)")

                # Log idempotent skip
                log_event(
                    event_type=AuditEventType.STORE_DATA,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=receiver_agency,
                    stage="receiver",
                    outcome=EventOutcome.SUCCESS,
                    details={
                        "action": "store_to_target_idempotent_skip",
                        "target_location": target_location,
                    },
                )

                return {
                    "status": "already_stored",
                    "target_location": target_location,
                }

            # Step 2: Upload files to target
            file_count = 0
            total_bytes = 0
            target_prefix = f"transfers/{sender_agency}/{transfer_session_id}/"

            for file_path in sorted(extracted_files_dir.rglob("*")):
                if file_path.is_file():
                    relative_path = file_path.relative_to(extracted_files_dir)
                    target_key = f"{target_prefix}{relative_path}"

                    file_size = file_path.stat().st_size

                    with open(file_path, "rb") as f:
                        self._upload_to_s3(target_key, f, file_size)

                    file_count += 1
                    total_bytes += file_size

            # Step 3: Create marker object (idempotency guard)
            stored_at = datetime.now(timezone.utc).isoformat()
            self._mark_stored(marker_key, transfer_session_id, file_count, total_bytes, stored_at)

            # Step 4: Log successful store
            log_event(
                event_type=AuditEventType.STORE_DATA,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.SUCCESS,
                bytes_transferred=total_bytes,
                details={
                    "action": "store_to_target_success",
                    "file_count": file_count,
                    "total_bytes": total_bytes,
                    "target_location": target_location,
                },
            )

            _logger.info(f"Successfully stored {file_count} files ({total_bytes} bytes) for transfer {transfer_session_id}")

            return {
                "status": "stored",
                "file_count": file_count,
                "total_bytes": total_bytes,
                "target_location": target_location,
                "stored_at": stored_at,
            }

        except StorageError:
            raise
        except Exception as e:
            error_msg = f"Failed to store to target: {str(e)}"
            _logger.error(error_msg)

            # Log failed store
            log_event(
                event_type=AuditEventType.STORE_DATA,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=receiver_agency,
                stage="receiver",
                outcome=EventOutcome.FAILURE,
                details={"action": "store_to_target_failed", "error": str(e)},
            )

            raise StorageError(error_msg) from e

    def _is_already_stored(self, marker_key: str) -> bool:
        """Check if marker object exists (idempotency guard).

        Args:
            marker_key: S3 key for marker object

        Returns:
            True if marker exists (already stored), False otherwise
        """
        try:
            self.s3_client._client.head_object(
                Bucket=self.target_bucket,
                Key=marker_key
            )
            return True
        except Exception:
            return False

    def _upload_to_s3(self, s3_key: str, file_obj, file_size: int) -> None:
        """Upload file to S3 target bucket.

        Args:
            s3_key: S3 object key
            file_obj: File object opened in binary mode
            file_size: File size in bytes

        Raises:
            StorageError: If upload fails
        """
        try:
            self.s3_client._client.put_object(
                Bucket=self.target_bucket,
                Key=s3_key,
                Body=file_obj,
                ContentLength=file_size
            )
        except Exception as e:
            error_msg = f"Failed to upload {s3_key} to s3://{self.target_bucket}/: {str(e)}"
            _logger.error(error_msg)
            raise StorageError(error_msg) from e

    def _mark_stored(
        self,
        marker_key: str,
        transfer_session_id: str,
        file_count: int,
        total_bytes: int,
        stored_at: str,
    ) -> None:
        """Create marker object to track stored transfer (idempotency guard).

        Args:
            marker_key: S3 key for marker object
            transfer_session_id: Transfer session ID
            file_count: Number of files stored
            total_bytes: Total bytes stored
            stored_at: ISO timestamp of store

        Raises:
            StorageError: If marker creation fails
        """
        try:
            marker_metadata = {
                "transfer_id": transfer_session_id,
                "stored_at": stored_at,
                "file_count": file_count,
                "total_bytes": total_bytes,
            }

            self.s3_client._client.put_object(
                Bucket=self.target_bucket,
                Key=marker_key,
                Body=json.dumps(marker_metadata).encode("utf-8"),
            )

            _logger.info(f"Created marker object {marker_key} for idempotency")

        except Exception as e:
            error_msg = f"Failed to create marker for {transfer_session_id}: {str(e)}"
            _logger.error(error_msg)
            raise StorageError(error_msg) from e
