from __future__ import annotations

"""Agent runtime entrypoints for the Redwood MVP foundation.

The agent module implements the core sender and receiver workflows for Day 1 MVP:
- Sender: Extract → Policy Check → Compress → Manifest → Stage
- Receiver: Validate → Decompress → Verify → Store

Both workflows include comprehensive audit logging and error handling.
"""

import hashlib
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from .audit.events import EventOutcome
from .audit.logger import (
    log_compress,
    log_extract_data,
    log_manifest_created,
    log_pipeline_complete,
    log_pipeline_start,
    log_policy_check,
    log_sftp_transfer_complete,
    log_sftp_transfer_start,
)
from .aws.s3 import S3Client
from .config import AgentConfig
from .exceptions import (
    ConfigurationError,
    StorageError,
)
from .logging_utils import get_logger, logging_context, prefix_log_message
from .models.manifest import (
    ChecksumAlgorithm,
    CompressionType,
    ManifestFile,
    TransferManifest,
    apply_archive_field_naming,
)
from .policy import PolicyApprover
from .receiver.landing import ReceiverLandingZone
from .receiver.store import ReceiverTargetStore
from .sftp import create_sftp_client_from_secrets_manager
from .storage.conventions import SenderStoragePath

# Create module logger (will auto-inject transfer_session_id from context)
LOGGER = get_logger("redwood_dataagent")

# Day 1 MVP uses SHA256 for checksums and gzip for compression
DEFAULT_CHECKSUM_ALGORITHM = ChecksumAlgorithm.SHA256
DEFAULT_COMPRESSION = CompressionType.GZIP
DEFAULT_DATA_FILE_NAME = "data.json"
DEFAULT_ARCHIVE_FILE_NAME = "transfer.tar.gz"
DEFAULT_MANIFEST_FILE_NAME = "manifest.json"
DEFAULT_RETRY_ATTEMPTS = 3

T = TypeVar("T")


def _retry_operation(operation_name: str, operation: Callable[[], T], attempts: int = DEFAULT_RETRY_ATTEMPTS) -> T:
    """Retry an operation for transient failures before raising StorageError."""
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - exercised via caller paths
            last_error = exc
            if attempt < attempts:
                LOGGER.warning(
                    prefix_log_message("Retrying operation after failure"),
                    extra={
                        "event": "operation_retry",
                        "operation": operation_name,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error": str(exc),
                    },
                )

    raise StorageError(
        f"{operation_name} failed after {attempts} attempts: {last_error}"
    ) from last_error


def _build_processed_marker_key(key: str) -> str:
    """Build marker object key for a processed incoming file."""
    if key.startswith("incoming/"):
        return key.replace("incoming/", "processed/", 1) + ".done"

    if "/incoming/" in key:
        return key.replace("/incoming/", "/processed/", 1) + ".done"

    return f"processed/{Path(key).name}.done"


def _extract_data(config: AgentConfig) -> None:
    """Placeholder extraction hook for future implementation.

    Day 1 expects sender agencies to provide a prepared source data file.
    Phase 2 can implement agency-side extraction logic here.
    """
    _ = config


def _scan_sender_directory(directory_path: str, aws_region: str) -> list[tuple[str, str]]:
    """Scan S3 directory for unprocessed files (files without .done marker).

    Parameters
    ----------
    directory_path : str
        S3 directory path (e.g., s3://bucket/incoming/)
    aws_region : str
        AWS region for S3 access

    Returns
    -------
    list[tuple[str, str]]
        List of (s3_path, file_name) tuples for files ready to process.
        Excludes files that have .done markers in processed/

    Raises
    ------
    StorageError
        If directory listing fails
    """
    try:
        parsed = _parse_s3_path(directory_path)
        if parsed is None:
            raise StorageError(
                f"Sender directory must be an S3 path, got: {directory_path}"
            )

        bucket, prefix = parsed
        client = S3Client(aws_region=aws_region)
        
        # List objects in the incoming directory
        response = client._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        files = []
        
        if "Contents" not in response:
            return []
        
        for obj in response["Contents"]:
            key = obj["Key"]
            # Skip if it's the prefix itself or is a directory marker
            if key == prefix or key.endswith("/"):
                continue
            
            file_name = Path(key).name
            
            # Skip if this is a marker file (.done files should not be processed)
            if file_name.endswith(".done"):
                LOGGER.debug(f"Skipping marker file: {key}")
                continue
            
            # Check if file has been processed (marker exists in processed/)
            # Construct absolute path: replace 'incoming/' with 'processed/'
            processed_marker_key = _build_processed_marker_key(key)
            try:
                client._client.head_object(Bucket=bucket, Key=processed_marker_key)
                LOGGER.debug(f"Skipping already processed file: {key}")
                continue
            except Exception:
                # Marker doesn't exist, file is ready to process
                pass
            
            s3_path = f"s3://{bucket}/{key}"
            files.append((s3_path, file_name))
        
        return files
    except Exception as e:
        raise StorageError(f"Failed to scan sender directory: {e}") from e


def _mark_file_processed(file_name: str, directory_path: str, aws_region: str) -> None:
    """Create a .done marker in processed/ directory after successful processing.

    Parameters
    ----------
    file_name : str
        Name of the file that was processed
    directory_path : str
        S3 directory path (e.g., s3://bucket/incoming/)
    aws_region : str
        AWS region for S3 access

    Raises
    ------
    StorageError
        If marker creation fails
    """
    try:
        parsed = _parse_s3_path(directory_path)
        if parsed is None:
            raise StorageError(
                f"Sender directory must be an S3 path, got: {directory_path}"
            )

        bucket, prefix = parsed
        client = S3Client(aws_region=aws_region)
        
        # Create marker in processed/ directory using absolute path
        # Replace 'incoming/' with 'processed/' in the prefix
        if not prefix.endswith("/"):
            prefix = f"{prefix}/"

        processed_prefix = prefix.replace("incoming/", "processed/", 1)
        marker_key = f"{processed_prefix}{file_name}.done"
        timestamp = datetime.now(timezone.utc).isoformat()
        marker_metadata = {
            "processed_at": timestamp,
            "original_file": file_name,
        }
        
        client._client.put_object(
            Bucket=bucket,
            Key=marker_key,
            Body=json.dumps(marker_metadata).encode("utf-8"),
        )
        LOGGER.info(prefix_log_message(f"Marked file as processed: {marker_key}"))
    except Exception as e:
        raise StorageError(f"Failed to mark file as processed: {e}") from e


def _parse_s3_path(path: str) -> tuple[str, str] | None:
    """Parse an S3 URL into bucket and key components.

    S3 paths have the format: s3://bucket-name/path/to/key

    Parameters
    ----------
    path : str
        S3 path or local file path

    Returns
    -------
    tuple[str, str] | None
        (bucket, key) if path is an S3 URL, None otherwise

    Example
    -------
    >>> _parse_s3_path("s3://my-bucket/transfers/sess-001/data.json")
    ("my-bucket", "transfers/sess-001/data.json")
    """
    if not path.startswith("s3://"):
        return None

    try:
        # Remove s3:// prefix
        path_without_scheme = path[5:]
        # Split on first slash
        parts = path_without_scheme.split("/", 1)
        if len(parts) == 2:
            bucket, key = parts
            if bucket and key:
                return bucket, key
    except (ValueError, IndexError):
        pass

    raise StorageError(f"Invalid S3 path format: {path}. Expected: s3://bucket/key")


def _download_from_s3(
    s3_path: str, destination_path: Path, aws_region: str
) -> dict[str, Any]:
    """Download a file from S3 to container filesystem (S3 → container).

    Helper to fetch sender's data file from sender-side S3 storage into
    the container's working directory for processing (policy check, compression, etc).

    Parameters
    ----------
    s3_path : str
        Full S3 URL (e.g., "s3://tts-core-dev-dot-data-staging/transfers/sess-001/data.json")
    destination_path : Path
        Path on the container filesystem where the S3 object will be written.
        Typically in a temporary working directory for staging.
    aws_region : str
        AWS region where the S3 bucket is located

    Returns
    -------
    dict[str, Any]
        Metadata about the downloaded file:
        - data_source: "s3_object"
        - s3_bucket: Source bucket name
        - s3_key: Source object key
        - file_name: Name of the downloaded file
        - file_size_bytes: Size in bytes

    Raises
    ------
    StorageError
        If S3 download fails (bucket not found, object not found, access denied, etc)
    """
    bucket, key = _parse_s3_path(s3_path)
    
    client = S3Client(aws_region=aws_region)
    client.download_file(bucket, key, destination_path)
    
    return {
        "data_source": "s3_object",
        "s3_bucket": bucket,
        "s3_key": key,
        "file_name": destination_path.name,
        "file_size_bytes": destination_path.stat().st_size,
    }


def _resolve_configured_file(file_path: str | None, label: str) -> Path | None:
    """Resolve a configured file path and fail when it does not exist.

    Returns None when the path is not configured. Raises StorageError when the
    path is missing or is not a regular file.
    """
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        raise StorageError(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise StorageError(f"{label} path is not a file: {path}")

    return path


def _prepare_sender_data_file(config: AgentConfig, working_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Load sender's data file from container filesystem or S3 into working directory.

    Implements flexible sourcing for Day 1 MVP:
    - For local testing: reads file from container filesystem (e.g., /tmp/data.json)
    - For cloud deployment: downloads file from sender-side S3 storage

    The loaded file is staged in the container's working directory for subsequent processing:
    policy validation → manifest generation → compression → upload to sender SFTP.

    Routing logic:
    - If path starts with "s3://": download from S3
    - Otherwise: treat as path on container filesystem

    Parameters
    ----------
    config : AgentConfig
        Runtime configuration containing:
        - sender_data_file: Path to source file (container path or s3://bucket/key)
        - aws_region: AWS region for S3 operations (if using S3 source)
    working_dir : Path
        Temporary working directory on the container filesystem where file will be staged.
        Typically created by the caller with tempfile.TemporaryDirectory.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        - staged_file_path: Path on container filesystem where the file was copied/downloaded
        - metadata: Dict describing the file source and size

    Raises
    ------
    StorageError
        If sender_data_file is not configured, source file doesn't exist on the
        container filesystem, is not a regular file, or S3 download fails
    """
    if not config.sender_data_file:
        _extract_data(config)
        raise StorageError(
            "Sender data file is required for Day 1. "
            "Set SENDER_DATA_FILE to a valid file path (local or s3://bucket/key)."
        )

    file_path = config.sender_data_file.strip()

    # Check if this is an S3 path
    if file_path.startswith("s3://"):
        try:
            # Create a staged file in working directory
            # Use the last component of the S3 key as the filename
            _, key = _parse_s3_path(file_path)
            file_name = Path(key).name or "data"
            staged_file = working_dir / file_name

            # Download from S3
            metadata = _download_from_s3(file_path, staged_file, config.aws_region)
            return staged_file, metadata
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to download from S3: {e}") from e

    # Otherwise, treat as local file path
    configured_file = _resolve_configured_file(file_path, "Sender data")
    if configured_file is not None:
        staged_file = working_dir / configured_file.name
        shutil.copy2(configured_file, staged_file)
        return staged_file, {
            "data_source": "sender_provided_file",
            "file_name": configured_file.name,
            "file_size_bytes": staged_file.stat().st_size,
        }

    _extract_data(config)
    raise StorageError(
        "Sender data file is required for Day 1. "
        "Set SENDER_DATA_FILE to a valid file path (local or s3://bucket/key)."
    )


def _write_sender_manifest_output(manifest: TransferManifest, manifest_path: Path) -> None:
    """Write the generated sender manifest to an output path.

    Applied field naming:
    - Source file: file_name, file_size_bytes, checksum_sha256
    - Archive file: zip_file_name, zip_file_size_bytes, checksum_sha256
    """
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_dict = manifest.model_dump(mode="json")
        # Rename archive fields for clarity before writing
        manifest_dict = apply_archive_field_naming(manifest_dict)

        with manifest_path.open("w", encoding="utf-8") as file_obj:
            json.dump(manifest_dict, file_obj, indent=2)
    except OSError as exc:
        raise StorageError(f"Failed to write sender manifest file {manifest_path}: {exc}") from exc


def _compute_checksum(file_path: Path, algorithm: ChecksumAlgorithm = DEFAULT_CHECKSUM_ALGORITHM) -> str:
    """Compute file checksum using specified algorithm.

    Parameters
    ----------
    file_path : Path
        Path to the file to checksum.
    algorithm : ChecksumAlgorithm, optional
        Algorithm to use. Defaults to SHA256.

    Returns
    -------
    str
        Hexadecimal digest of the file.

    Raises
    ------
    StorageError
        If the file cannot be read or algorithm is unsupported.
    """
    if algorithm != ChecksumAlgorithm.SHA256:
        raise StorageError(f"Unsupported checksum algorithm: {algorithm}")

    hash_obj = hashlib.sha256()
    try:
        with file_path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(8192), b""):
                hash_obj.update(chunk)
    except OSError as e:
        raise StorageError(f"Failed to read file {file_path}: {e}")

    return hash_obj.hexdigest()


def _safe_archive_member_name(file_name: str) -> str:
    """Validate archive member name to avoid unsafe paths in produced tarballs."""
    member_path = Path(file_name)
    if not file_name or file_name in {".", ".."}:
        raise StorageError("Archive member name cannot be empty or traversal markers")
    if member_path.is_absolute() or ".." in member_path.parts:
        raise StorageError(f"Unsafe archive member name: {file_name}")

    return file_name


def _create_sender_workflow(config: AgentConfig) -> int:
    """Execute sender-side transfer workflow.

    Implements: Extract → Policy → Compress → Manifest → Stage

    Scans SENDER_DATA_DIRECTORY for new files to process. Files marked with .done
    in processed/ directory are skipped. After successful processing, creates a
    .done marker to prevent reprocessing.

    Parameters
    ----------
    config : AgentConfig
        Validated runtime configuration.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    try:
        if not config.sender_data_directory:
            LOGGER.warning(
                prefix_log_message(
                    "Sender data directory not configured. "
                    "Set SENDER_DATA_DIRECTORY to a valid S3 directory path (e.g., s3://bucket/incoming/)",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                )
            )
            return 0

        # Scan directory for new files
        LOGGER.info(
            prefix_log_message(
                "Scanning sender directory for new files",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_scan_start", "directory": config.sender_data_directory},
        )
        files_to_process = _retry_operation(
            "detect_files",
            lambda: _scan_sender_directory(config.sender_data_directory, config.aws_region),
        )

        if not files_to_process:
            LOGGER.info(
                prefix_log_message(
                    "No new file read. Exiting sender workflow (idempotent).",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={"event": "sender_no_files", "directory": config.sender_data_directory},
            )
            return 0

        LOGGER.info(
            prefix_log_message(
                f"Found {len(files_to_process)} file(s) to process in sender directory",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_files_found", "file_count": len(files_to_process)},
        )

        # Process the first file (Day 1 MVP processes one at a time)
        s3_path, file_name = files_to_process[0]
        
        LOGGER.info(
            prefix_log_message(
                f"Processing file: {file_name}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_process_start", "file_name": file_name, "s3_path": s3_path},
        )

        # 1. Log pipeline start
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Download the file from S3
            try:
                bucket, key = _parse_s3_path(s3_path)
                client = S3Client(aws_region=config.aws_region)
                staged_file = tmpdir_path / file_name
                _retry_operation(
                    "download_sender_file",
                    lambda: client.download_file(bucket, key, staged_file),
                )

                extract_details = {
                    "data_source": "s3_object",
                    "s3_path": s3_path,
                    "file_name": file_name,
                    "file_size_bytes": staged_file.stat().st_size,
                }
            except Exception as e:
                log_extract_data(
                    transfer_session_id=config.transfer_session_id,
                    sender_agency=config.sender_agency,
                    receiver_agency=config.receiver_agency,
                    outcome=EventOutcome.FAILURE,
                    details={
                        "step": "detect",
                        "selected_path": s3_path,
                        "error": f"Failed to download file: {e}",
                    },
                )
                log_pipeline_complete(
                    transfer_session_id=config.transfer_session_id,
                    sender_agency=config.sender_agency,
                    receiver_agency=config.receiver_agency,
                    outcome=EventOutcome.FAILURE,
                    details={"error": f"Failed to download file: {e}"},
                )
                raise StorageError(f"Failed to download {s3_path}: {e}") from e

            LOGGER.info(
                prefix_log_message(
                    f"File read successfully: {file_name}",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_file_read",
                    "file_name": file_name,
                    "file_size_bytes": extract_details.get("file_size_bytes"),
                },
            )

            log_extract_data(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details=extract_details,
            )

            # 2. Policy approval check
            approver = PolicyApprover()
            is_approved = approver.approve_transfer(
                config.sender_agency,
                1,
            )

            if not is_approved:
                log_policy_check(
                    transfer_session_id=config.transfer_session_id,
                    sender_agency=config.sender_agency,
                    receiver_agency=config.receiver_agency,
                    outcome=EventOutcome.FAILURE,
                    details={"reason": "Policy approval denied", "file_count": 1},
                )
                return 1

            log_policy_check(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={"file_count": 1},
            )

            # 3. Compress data
            archive_path = tmpdir_path / DEFAULT_ARCHIVE_FILE_NAME
            archive_member_name = _safe_archive_member_name(staged_file.name)
            try:
                _retry_operation(
                    "compress_sender_data",
                    lambda: _compress_sender_data(archive_path, staged_file, archive_member_name),
                )
            except Exception as e:
                log_compress(
                    transfer_session_id=config.transfer_session_id,
                    sender_agency=config.sender_agency,
                    receiver_agency=config.receiver_agency,
                    outcome=EventOutcome.FAILURE,
                    details={"step": "compress", "source_file_name": staged_file.name, "error": str(e)},
                )
                raise

            log_compress(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={
                    "compression_type": DEFAULT_COMPRESSION.value,
                    "source_file_name": staged_file.name,
                    "source_size_bytes": staged_file.stat().st_size,
                    "compressed_size_bytes": archive_path.stat().st_size,
                },
            )

            # Include both source file(s) and the archive in manifest
            manifest_files = [
                ManifestFile(
                    file_name=file_name,  # Original source file
                    file_size_bytes=staged_file.stat().st_size,
                    checksum_sha256=_compute_checksum(staged_file, DEFAULT_CHECKSUM_ALGORITHM),
                ),
                ManifestFile(
                    file_name=archive_path.name,  # Compressed archive
                    file_size_bytes=archive_path.stat().st_size,
                    checksum_sha256=_compute_checksum(archive_path, DEFAULT_CHECKSUM_ALGORITHM),
                ),
            ]

            manifest = TransferManifest(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                compression_type=DEFAULT_COMPRESSION,
                total_file_count=len(manifest_files),
                files=manifest_files,
            )

            manifest_path = tmpdir_path / DEFAULT_MANIFEST_FILE_NAME
            try:
                _retry_operation(
                    "write_manifest",
                    lambda: _write_sender_manifest_output(manifest, manifest_path),
                )
            except Exception as e:
                log_manifest_created(
                    transfer_session_id=config.transfer_session_id,
                    sender_agency=config.sender_agency,
                    receiver_agency=config.receiver_agency,
                    outcome=EventOutcome.FAILURE,
                    details={"step": "manifest", "error": str(e)},
                )
                raise

            log_manifest_created(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={
                    "manifest_path": SenderStoragePath.transfers(
                        config.transfer_session_id,
                        manifest_path.name,
                    ),
                    "payload_file_count": manifest.total_file_count,
                    "archive_name": archive_path.name,
                },
            )

            # 4. Upload artifacts to sender staging bucket
            staging_client = S3Client(aws_region=config.aws_region)
            total_staged_bytes = 0
            staged_artifacts: list[tuple[Path, str]] = []
            for artifact_path in (archive_path, manifest_path):
                staging_key = SenderStoragePath.transfers(
                    config.transfer_session_id,
                    artifact_path.name,
                )
                try:
                    _retry_operation(
                        "stage_upload",
                        lambda: staging_client.upload_file(
                            artifact_path, config.sender_staging_bucket, staging_key
                        ),
                    )
                except Exception:
                    raise

                total_staged_bytes += artifact_path.stat().st_size
                staged_artifacts.append((artifact_path, staging_key))
                LOGGER.info(
                    prefix_log_message(
                        f"Staged artifact to S3: {artifact_path.name}",
                        agent_mode=config.agent_mode,
                        transfer_session_id=config.transfer_session_id,
                    ),
                    extra={
                        "event": "sender_artifact_staged",
                        "bucket": config.sender_staging_bucket,
                        "key": staging_key,
                    },
                )

            # 5. Upload staged artifacts to receiver SFTP endpoints
            sftp_client = create_sftp_client_from_secrets_manager(
                sftp_endpoints=config.sftp_endpoints,
                secrets_manager_name=config.sftp_secrets_manager_name,
                aws_region=config.aws_region,
            )
            primary_sftp_endpoint = config.sftp_endpoints[0]
            total_sftp_uploaded_bytes = 0
            log_sftp_transfer_start(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                destination_host=primary_sftp_endpoint,
                details={
                    "step": "sftp_upload",
                    "artifact_count": len(staged_artifacts),
                    "endpoints": config.sftp_endpoints,
                },
            )

            for artifact_path, _staging_key in staged_artifacts:
                remote_path = f"/{config.sender_agency}/{config.transfer_session_id}/{artifact_path.name}"
                try:
                    upload_metadata = _retry_operation(
                        "sftp_upload",
                        lambda: sftp_client.upload_file(artifact_path, remote_path),
                    )
                except Exception as e:
                    log_sftp_transfer_complete(
                        transfer_session_id=config.transfer_session_id,
                        sender_agency=config.sender_agency,
                        receiver_agency=config.receiver_agency,
                        destination_host=primary_sftp_endpoint,
                        bytes_transferred=total_sftp_uploaded_bytes,
                        outcome=EventOutcome.FAILURE,
                        details={
                            "step": "sftp_upload",
                            "remote_path": remote_path,
                            "error": str(e),
                        },
                    )
                    raise

                total_sftp_uploaded_bytes += int(upload_metadata.get("file_size_bytes", 0))
                LOGGER.info(
                    prefix_log_message(
                        f"Uploaded artifact to SFTP: {artifact_path.name}",
                        agent_mode=config.agent_mode,
                        transfer_session_id=config.transfer_session_id,
                    ),
                    extra={
                        "event": "sender_artifact_uploaded_sftp",
                        "remote_path": remote_path,
                        "endpoint": upload_metadata.get("endpoint", primary_sftp_endpoint),
                    },
                )

            log_sftp_transfer_complete(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                destination_host=primary_sftp_endpoint,
                outcome=EventOutcome.SUCCESS,
                bytes_transferred=total_sftp_uploaded_bytes,
                details={
                    "step": "sftp_upload",
                    "artifact_count": len(staged_artifacts),
                    "remote_prefix": f"/{config.sender_agency}/{config.transfer_session_id}/",
                    "staging_prefix": f"transfers/{config.transfer_session_id}/",
                    "staged_bytes": total_staged_bytes,
                },
            )

            # 6. Mark file as processed
            _retry_operation(
                "mark_file_processed",
                lambda: _mark_file_processed(file_name, config.sender_data_directory, config.aws_region),
            )
            LOGGER.info(
                prefix_log_message(
                    f"File marked as processed and moved to processed folder: {file_name}",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_file_marked",
                    "file_name": file_name,
                    "marker_location": f"{config.sender_data_directory}../processed/{file_name}.done",
                },
            )

            LOGGER.info(
                prefix_log_message(
                    "Sender workflow complete",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_complete",
                    "session_id": config.transfer_session_id,
                    "manifest": manifest.model_dump(),
                    "staged_artifacts": [
                        SenderStoragePath.transfers(
                            config.transfer_session_id,
                            archive_path.name,
                        ),
                        SenderStoragePath.transfers(
                            config.transfer_session_id,
                            manifest_path.name,
                        ),
                    ],
                },
            )

        # Pipeline completion
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
        )

        return 0

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Sender workflow failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_error", "error_type": type(e).__name__},
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(e)},
        )
        return 1


def _compress_sender_data(archive_path: Path, staged_file: Path, archive_member_name: str) -> None:
    """Create transfer archive for sender payload."""
    with tarfile.open(archive_path, "w:gz") as tar:  # NOSONAR
        tar.add(staged_file, arcname=archive_member_name)


def _process_single_receiver_transfer(
    landing_zone: "ReceiverLandingZone",
    target_store: "ReceiverTargetStore",
    config: AgentConfig,
    sender_agency: str,
    transfer_session_id: str,
) -> int:
    """Fetch, validate, decompress, and store one transfer from the landing bucket.

    Parameters
    ----------
    landing_zone : ReceiverLandingZone
    target_store : ReceiverTargetStore
    config : AgentConfig
    sender_agency : str
        Discovered sender agency code (e.g., "dot").
    transfer_session_id : str
        Discovered transfer session ID from the S3 folder name.

    Returns
    -------
    int
        0 on success, 1 on failure.
    """
    try:
        archive_bytes, manifest_dict = _retry_operation(
            "landing_fetch",
            lambda: landing_zone.fetch_from_landing_bucket(
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=config.receiver_agency,
            ),
        )

        manifest = _retry_operation(
            "manifest_validate",
            lambda: landing_zone.validate_manifest(
                manifest_dict=manifest_dict,
                archive_bytes=archive_bytes,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=config.receiver_agency,
            ),
        )

        # Guardrail: manifest identity must match what we discovered from S3.
        if manifest.transfer_session_id != transfer_session_id:
            raise StorageError(
                "Manifest transfer_session_id mismatch: "
                f"expected {transfer_session_id}, got {manifest.transfer_session_id}"
            )
        if manifest.receiver_agency and manifest.receiver_agency != config.receiver_agency:
            raise StorageError(
                "Manifest receiver_agency mismatch: "
                f"expected {config.receiver_agency}, got {manifest.receiver_agency}"
            )

        with tempfile.TemporaryDirectory(prefix="redwood-receiver-") as tmpdir:
            extraction_metadata = _retry_operation(
                "decompress",
                lambda: landing_zone.decompress_archive(
                    archive_bytes=archive_bytes,
                    target_directory=Path(tmpdir),
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                ),
            )

            _retry_operation(
                "store_to_target",
                lambda: target_store.store_to_target(
                    extracted_files_dir=Path(tmpdir),
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                ),
            )

        return 0

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Transfer from {sender_agency} failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=transfer_session_id,
            ),
            extra={
                "event": "receiver_transfer_error",
                "sender_agency": sender_agency,
                "transfer_session_id": transfer_session_id,
                "error_type": type(e).__name__,
            },
        )
        return 1


def _create_receiver_workflow(config: AgentConfig) -> int:
    """Execute receiver-side transfer workflow.

    Polls all sender agency folders in the landing bucket and processes every
    pending transfer session found.  The target-store idempotency marker prevents
    re-processing already-stored sessions.

    Returns 0 when all discovered transfers succeed (or there is nothing to do).
    Returns 1 if any individual transfer fails.
    """
    try:
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
        )

        s3_client = S3Client(aws_region=config.aws_region)
        landing_zone = ReceiverLandingZone(
            s3_client=s3_client,
            landing_bucket=config.receiver_landing_bucket,
            environment=config.environment,
        )
        target_store = ReceiverTargetStore(
            s3_client=s3_client,
            target_bucket=config.receiver_target_bucket,
            environment=config.environment,
        )

        # Scan the landing bucket for all sender agency folders.
        sender_agencies = _retry_operation(
            "list_sender_agencies",
            landing_zone.list_sender_agencies,
        )

        if not sender_agencies:
            LOGGER.info(
                prefix_log_message(
                    "No sender agency folders found in landing bucket; nothing to process.",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={"event": "receiver_no_senders", "bucket": config.receiver_landing_bucket},
            )
            log_pipeline_complete(
                transfer_session_id=config.transfer_session_id,
                sender_agency="",
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
            )
            return 0

        LOGGER.debug(
            prefix_log_message(
                f"Found {len(sender_agencies)} sender agency folder(s): {sender_agencies}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "receiver_senders_found", "sender_agencies": sender_agencies},
        )

        processed = 0
        already_processed = 0
        failed = 0
        processed_transfers: list[dict[str, str]] = []
        already_processed_transfers: list[dict[str, str]] = []
        failed_transfers: list[dict[str, str]] = []
        for sender_agency in sender_agencies:
            transfer_sessions = _retry_operation(
                f"list_pending_transfers_{sender_agency}",
                lambda sa=sender_agency: landing_zone.list_pending_transfers(sa),
            )
            for transfer_session_id in transfer_sessions:
                with logging_context(transfer_session_id):
                    # Pre-check target idempotency marker so already-complete transfers
                    # are not fetched/validated/decompressed again.
                    if target_store.is_transfer_already_stored(transfer_session_id, sender_agency):
                        already_processed += 1
                        already_processed_transfers.append(
                            {
                                "sender_agency": sender_agency,
                                "transfer_session_id": transfer_session_id,
                            }
                        )
                        LOGGER.debug(
                            prefix_log_message(
                                f"Transfer from {sender_agency} already marked done in target; skipping.",
                                agent_mode=config.agent_mode,
                            ),
                            extra={
                                "event": "receiver_transfer_skip_done",
                                "sender_agency": sender_agency,
                                "transfer_session_id": transfer_session_id,
                            },
                        )
                        continue

                    LOGGER.info(
                        prefix_log_message(
                            f"Processing transfer from {sender_agency}",
                            agent_mode=config.agent_mode,
                        ),
                        extra={
                            "event": "receiver_transfer_start",
                            "sender_agency": sender_agency,
                            "transfer_session_id": transfer_session_id,
                        },
                    )
                    result = _process_single_receiver_transfer(
                        landing_zone, target_store, config, sender_agency, transfer_session_id
                    )
                    if result == 0:
                        processed += 1
                        processed_transfers.append(
                            {
                                "sender_agency": sender_agency,
                                "transfer_session_id": transfer_session_id,
                            }
                        )
                    else:
                        failed += 1
                        failed_transfers.append(
                            {
                                "sender_agency": sender_agency,
                                "transfer_session_id": transfer_session_id,
                            }
                        )

        recent_already_processed: list[dict[str, str]] = []

        if processed == 0 and failed == 0:
            LOGGER.info(
                prefix_log_message(
                    "No new files to process. Exiting receiver workflow (idempotent).",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "receiver_no_new_files",
                    "already_processed": already_processed,
                    "bucket": config.receiver_landing_bucket,
                },
            )
        else:
            recent_already_processed = sorted(
                already_processed_transfers,
                key=lambda item: item["transfer_session_id"],
                reverse=True,
            )[:3]
            recent_already_processed_refs = [
                f"{item['sender_agency']}/{item['transfer_session_id']}"
                for item in recent_already_processed
            ]

            LOGGER.info(
                prefix_log_message(
                    "Receiver scan complete: "
                    f"{processed} processed, {already_processed} already processed, {failed} failed "
                    f"(last_3_already_processed={recent_already_processed_refs})",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "receiver_scan_complete",
                    "processed": processed,
                    "already_processed": already_processed,
                    "failed": failed,
                    "last_3_already_processed": recent_already_processed,
                },
            )

        outcome = EventOutcome.SUCCESS if failed == 0 else EventOutcome.FAILURE
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
            outcome=outcome,
            details={
                "processed": processed,
                "already_processed": already_processed,
                "failed": failed,
                "processed_transfers": processed_transfers,
                "last_3_already_processed": recent_already_processed,
                "failed_transfers": failed_transfers,
            },
        )

        return 0 if failed == 0 else 1

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Receiver workflow failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "receiver_error", "error_type": type(e).__name__},
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(e)},
        )
        return 1


def run_agent(config: AgentConfig) -> int:
    """Run the agent workflow for the configured mode.

    Routes to sender or receiver workflow based on config.agent_mode.
    All workflows include audit logging and error handling.

    Parameters
    ----------
    config : AgentConfig
        Validated runtime configuration with agency and environment settings.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    if config.agent_mode == "sender":
        return _create_sender_workflow(config)
    elif config.agent_mode == "receiver":
        return _create_receiver_workflow(config)
    else:
        raise ConfigurationError(
            f"Invalid agent mode: {config.agent_mode}. "
            f"Must be 'sender' or 'receiver'."
        )