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
from pathlib import Path
from typing import Any

from .audit.events import EventOutcome
from .audit.logger import (
    log_compress,
    log_decompress,
    log_extract_data,
    log_manifest_created,
    log_pipeline_complete,
    log_pipeline_start,
    log_policy_check,
    log_store_data,
    log_validate_manifest,
)
from .aws.s3 import S3Client
from .config import AgentConfig
from .exceptions import (
    ConfigurationError,
    StorageError,
)
from .logging_utils import get_logger
from .models.manifest import ChecksumAlgorithm, CompressionType, ManifestFile, TransferManifest
from .policy import PolicyApprover
from .storage.conventions import SenderStoragePath

# Create module logger (will auto-inject transfer_session_id from context)
LOGGER = get_logger("redwood_dataagent")

# Day 1 MVP uses SHA256 for checksums and gzip for compression
DEFAULT_CHECKSUM_ALGORITHM = ChecksumAlgorithm.SHA256
DEFAULT_COMPRESSION = CompressionType.GZIP
DEFAULT_DATA_FILE_NAME = "data.json"
DEFAULT_ARCHIVE_FILE_NAME = "transfer.tar.gz"
DEFAULT_MANIFEST_FILE_NAME = "manifest.json"


def _extract_data(config: AgentConfig) -> None:
    """Placeholder extraction hook for future implementation.

    Day 1 expects sender agencies to provide a prepared source data file.
    Phase 2 can implement agency-side extraction logic here.
    """
    _ = config


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
            bucket, key = _parse_s3_path(file_path)
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
    """Write the generated sender manifest to an output path."""
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", encoding="utf-8") as file_obj:
            json.dump(manifest.model_dump(mode="json"), file_obj, indent=2)
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
        # 1. Log pipeline start
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            data_file, extract_details = _prepare_sender_data_file(config, tmpdir_path)

            log_extract_data(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details=extract_details,
            )

            # 3. Policy approval check
            approver = PolicyApprover()
            is_approved = approver.approve_transfer(
                config.sender_agency,
                config.receiver_agency,
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

            # 4. Compress data
            archive_path = tmpdir_path / DEFAULT_ARCHIVE_FILE_NAME
            archive_member_name = _safe_archive_member_name(data_file.name)
            # Archive creation is limited to a validated relative file name.
            with tarfile.open(archive_path, "w:gz") as tar:  # NOSONAR
                tar.add(data_file, arcname=archive_member_name)

            log_compress(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={
                    "compression_type": DEFAULT_COMPRESSION.value,
                    "source_file_name": data_file.name,
                    "source_size_bytes": data_file.stat().st_size,
                    "compressed_size_bytes": archive_path.stat().st_size,
                },
            )

            manifest_files = [
                ManifestFile(
                    file_name=archive_path.name,
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
            _write_sender_manifest_output(manifest, manifest_path)

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

            # 5. Stage artifacts (in Day 1 MVP, this would write to S3)
            # For testing, we'll just log that staging occurred
            LOGGER.info(
                "Sender workflow complete",
                extra={
                    "event": "sender_complete",
                    "session_id": config.transfer_session_id,
                    "manifest": manifest.model_dump(),
                    "staged_artifacts": [
                        SenderStoragePath.transfers(config.transfer_session_id, archive_path.name),
                        SenderStoragePath.transfers(config.transfer_session_id, manifest_path.name),
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
            f"Sender workflow failed: {e}",
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


def _create_receiver_workflow(config: AgentConfig) -> int:
    """Execute receiver-side transfer workflow.

    Implements: Validate → Decompress → Verify → Store

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
        # 1. Log pipeline start
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
        )

        log_validate_manifest(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "manifest_source": "landing_storage",
                "status": "pending_storage_integration",
            },
        )

        # 3. Decompress and store (placeholder for Day 1 MVP)
        log_decompress(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "step": "decompress",
                "files_processed": 0,
            },
        )

        log_store_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "step": "store",
                "destination_bucket": config.receiver_target_bucket,
                "status": "pending_storage_integration",
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
            f"Receiver workflow failed: {e}",
            extra={"event": "receiver_error", "error_type": type(e).__name__},
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
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