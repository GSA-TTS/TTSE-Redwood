"""AWS S3 client utilities for object storage operations.

This module provides S3 utilities for bidirectional file transfers:
- Download: S3 → local filesystem (reading data from S3)
- Upload: local filesystem → S3 (writing data to S3)

Supports sender and receiver storage buckets with error handling and logging.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client as BotoS3Client

from ..exceptions import StorageError
from ..logging_utils import get_logger

LOGGER = get_logger("redwood_dataagent")


def _get_positive_int_env(name: str, default: int) -> int:
    """Return a positive integer env var value, falling back to default when invalid."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        parsed = int(raw_value)
        if parsed > 0:
            return parsed
    except ValueError:
        pass

    LOGGER.warning(
        "Invalid environment value for transfer tuning; using default",
        extra={"event": "s3_transfer_env_invalid", "name": name, "value": raw_value, "default": default},
    )
    return default


class S3Client:
    """Wrapper for AWS S3 bidirectional file operations.

    Provides methods to:
    - Download files from S3 to local filesystem
    - Upload files from local filesystem to S3
    - Check S3 object existence without throwing exceptions

    All operations include proper error detection and translation to StorageError
    for consistent exception handling across the agent.
    """

    def __init__(self, aws_region: str = "us-east-1"):
        """Initialize S3 client.

        Parameters
        ----------
        aws_region : str, optional
            AWS region for SDK operations. Defaults to "us-east-1".

        Environment-based transfer tuning
        ---------------------------------
        S3_MULTIPART_THRESHOLD_MB
            Multipart transfer threshold in MB. Default: 64.
        S3_MULTIPART_CHUNKSIZE_MB
            Multipart chunk size in MB. Default: 64.
        S3_TRANSFER_MAX_CONCURRENCY
            Maximum concurrent transfer threads. Default: 8.
        S3_TRANSFER_DOWNLOAD_ATTEMPTS
            Number of download attempts per transfer. Default: 5.
        """
        try:
            import boto3
            try:
                from boto3.s3.transfer import TransferConfig
            except Exception:
                # Test environments may mock boto3 without package submodules.
                class TransferConfig:  # type: ignore[no-redef]
                    def __init__(self, **_: object):
                        pass

            multipart_threshold_mb = _get_positive_int_env("S3_MULTIPART_THRESHOLD_MB", 64)
            multipart_chunksize_mb = _get_positive_int_env("S3_MULTIPART_CHUNKSIZE_MB", 64)
            max_concurrency = _get_positive_int_env("S3_TRANSFER_MAX_CONCURRENCY", 8)
            download_attempts = _get_positive_int_env("S3_TRANSFER_DOWNLOAD_ATTEMPTS", 5)

            self._transfer_config = TransferConfig(
                multipart_threshold=multipart_threshold_mb * 1024 * 1024,
                multipart_chunksize=multipart_chunksize_mb * 1024 * 1024,
                max_concurrency=max_concurrency,
                num_download_attempts=download_attempts,
            )

            self._client: BotoS3Client = boto3.client("s3", region_name=aws_region)
            self._region = aws_region

            LOGGER.debug(
                "Initialized S3 transfer configuration",
                extra={
                    "event": "s3_transfer_config_initialized",
                    "region": aws_region,
                    "multipart_threshold_mb": multipart_threshold_mb,
                    "multipart_chunksize_mb": multipart_chunksize_mb,
                    "max_concurrency": max_concurrency,
                    "download_attempts": download_attempts,
                },
            )
        except ImportError as e:
            raise ImportError(
                "boto3 is required for S3 operations. Install with: pip install boto3"
            ) from e

    def download_file(self, bucket: str, key: str, destination_path: Path) -> None:
        """Download a file from S3 to container filesystem (S3 → container).

        Reads an object from S3 and writes it to the specified path on the
        container's filesystem. Creates parent directories if they don't exist.

        Parameters
        ----------
        bucket : str
            S3 bucket name (e.g., "tts-core-dev-dot-data-staging")
        key : str
            S3 object key (e.g., "transfers/abc-123/data.json")
        destination_path : Path
            Path on the container filesystem where the downloaded file will be written.
            Parent directories will be created automatically.

        Raises
        ------
        StorageError
            If the S3 object cannot be read, bucket is inaccessible, object
            does not exist, or the file cannot be written to the container filesystem.

        Example
        -------
        >>> client = S3Client("us-east-1")
        >>> # Download sender's data file from S3 for processing
        >>> client.download_file(
        ...     "tts-core-dev-dot-data-staging",
        ...     "transfers/sess-001/data.json",
        ...     Path("/tmp/sender-data.json")  # path on container
        ... )
        """
        try:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(
                bucket,
                key,
                str(destination_path),
                Config=self._transfer_config,
            )
            LOGGER.debug(
                "Downloaded S3 object",
                extra={
                    "event": "s3_download",
                    "bucket": bucket,
                    "key": key,
                    "destination_path": str(destination_path),
                    "file_size_bytes": destination_path.stat().st_size,
                },
            )
        except self._client.exceptions.NoSuchBucket:
            raise StorageError(f"S3 bucket does not exist: {bucket}") from None
        except self._client.exceptions.NoSuchKey:
            raise StorageError(f"S3 object does not exist: s3://{bucket}/{key}") from None
        except OSError as e:
            raise StorageError(f"Failed to write file to {destination_path}: {e}") from e
        except Exception as e:
            raise StorageError(
                f"Failed to download S3 object s3://{bucket}/{key}: {e}"
            ) from e

    def upload_file(self, source_path: Path, bucket: str, key: str) -> None:
        """Upload a file from container filesystem to S3 (container → S3).

        Reads a file from the container's filesystem and writes it to S3.
        Validates that the source file exists and is a regular file before upload.

        Parameters
        ----------
        source_path : Path
            Path on the container filesystem to read from. Must exist and be a file
            (not a directory or symlink).
        bucket : str
            S3 bucket name where the file will be stored
            (e.g., "tts-core-dev-dot-data-staging")
        key : str
            S3 object key for the uploaded file
            (e.g., "transfers/sess-001/compressed.tar.gz")

        Raises
        ------
        StorageError
            If the source file doesn't exist, is not a regular file,
            cannot be read from the container filesystem, or the S3 upload fails.

        Example
        -------
        >>> client = S3Client("us-east-1")
        >>> # Upload compressed payload to sender staging area
        >>> client.upload_file(
        ...     Path("/tmp/payload.tar.gz"),  # path on container
        ...     "tts-core-dev-dot-data-staging",
        ...     "transfers/sess-001/payload.tar.gz"
        ... )
        """
        try:
            if not source_path.exists():
                raise StorageError(f"Local file does not exist: {source_path}")
            if not source_path.is_file():
                raise StorageError(f"Path is not a file: {source_path}")

            self._client.upload_file(
                str(source_path),
                bucket,
                key,
                Config=self._transfer_config,
            )
            LOGGER.debug(
                "Uploaded file to S3",
                extra={
                    "event": "s3_upload",
                    "bucket": bucket,
                    "key": key,
                    "source_path": str(source_path),
                    "file_size_bytes": source_path.stat().st_size,
                },
            )
        except self._client.exceptions.NoSuchBucket:
            raise StorageError(f"S3 bucket does not exist: {bucket}") from None
        except OSError as e:
            raise StorageError(f"Failed to read file {source_path}: {e}") from e
        except Exception as e:
            raise StorageError(
                f"Failed to upload file to s3://{bucket}/{key}: {e}"
            ) from e

    def object_exists(self, bucket: str, key: str) -> bool:
        """Check if an S3 object exists without raising exceptions.

        Non-throwing method to check object existence. Returns False for any
        error condition (bucket not found, object not found, access denied, etc).
        Useful for optional/conditional file handling.

        Parameters
        ----------
        bucket : str
            S3 bucket name to check
        key : str
            S3 object key to check for existence

        Returns
        -------
        bool
            True if the object exists and is readable, False otherwise.
            Also returns False on any errors (permission denied, network issues, etc).

        Example
        -------
        >>> client = S3Client("us-east-1")
        >>> if client.object_exists("tts-core-dev-dot-data-staging", "transfers/sess-001/manifest.json"):
        ...     # Only download manifest if it exists
        ...     client.download_file(...)
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except self._client.exceptions.NoSuchBucket:
            return False
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception:
            return False
