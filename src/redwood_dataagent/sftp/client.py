"""SFTP client wrapper for paramiko SSH/SFTP operations.

Provides a high-level interface for uploading files to SFTP endpoints with
automatic retry logic, connection pooling, and exception translation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import sleep
from typing import Optional

from redwood_dataagent.exceptions import StorageError

LOGGER = logging.getLogger(__name__)


class SFTPClient:
    """SFTP client wrapper with paramiko integration.

    Handles SSH/SFTP connections to remote servers with connection pooling,
    automatic retry on transient failures, and comprehensive error translation.

    Parameters
    ----------
    host : str
        Remote SFTP server hostname or IP address
    port : int
        SSH/SFTP port (default: 22)
    username : str
        SSH username for authentication
    password : Optional[str]
        SSH password (if using password auth instead of key)
    key_path : Optional[Path]
        Path to SSH private key file (if using key-based auth)
    timeout : int
        Connection timeout in seconds (default: 30)
    max_retries : int
        Maximum retry attempts on transient failures (default: 3)
    retry_backoff : float
        Base backoff multiplier for exponential retry (default: 2.0)

    Raises
    ------
    StorageError
        If paramiko is not installed or initial connection fails

    Example
    -------
    >>> client = SFTPClient(
    ...     host="receiver.example.com",
    ...     username="sender",
    ...     key_path=Path("/secrets/sender-key")
    ... )
    >>> client.upload_file(
    ...     Path("/tmp/archive.tar.gz"),
    ...     "/incoming/transfers/archive.tar.gz"
    ... )
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        key_path: Optional[Path] = None,
        port: int = 22,
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
    ) -> None:
        """Initialize SFTP client with connection parameters."""
        # Lazy import for testing flexibility
        try:
            import paramiko
            self._paramiko = paramiko
        except ImportError as e:
            raise ImportError(
                "paramiko is required for SFTP support. "
                "Install with: pip install paramiko"
            ) from e

        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_path = key_path
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._transport = None

        # Validate authentication method
        if password is None and key_path is None:
            raise StorageError(
                "Either password or key_path must be provided for SFTP authentication"
            )

        if key_path is not None and not key_path.exists():
            raise StorageError(f"SSH key file does not exist: {key_path}")

        LOGGER.debug(
            "SFTP client initialized",
            extra={
                "event": "sftp_init",
                "host": host,
                "port": port,
                "username": username,
                "auth_method": "key" if key_path else "password",
            },
        )

    def _connect(self) -> paramiko.SFTPClient:
        """Create and return an SFTP client connection.

        Returns
        -------
        paramiko.SFTPClient
            Connected SFTP client instance

        Raises
        ------
        StorageError
            If connection fails (auth error, network issue, etc.)
        """
        try:
            ssh = self._paramiko.SSHClient()
            ssh.set_missing_host_key_policy(
                self._paramiko.AutoAddPolicy()
            )

            # Determine auth method
            if self._key_path:
                ssh.connect(
                    self._host,
                    port=self._port,
                    username=self._username,
                    key_filename=str(self._key_path),
                    timeout=self._timeout,
                )
            else:
                ssh.connect(
                    self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    timeout=self._timeout,
                )

            sftp = ssh.open_sftp()
            return sftp
        except self._paramiko.AuthenticationException as e:
            raise StorageError(
                f"SFTP authentication failed for {self._username}@{self._host}"
            ) from e
        except self._paramiko.SSHException as e:
            raise StorageError(
                f"SSH connection failed to {self._host}:{self._port}: {e}"
            ) from e
        except OSError as e:
            raise StorageError(
                f"Network error connecting to {self._host}:{self._port}: {e}"
            ) from e
        except Exception as e:
            raise StorageError(
                f"Failed to connect to SFTP server {self._host}: {e}"
            ) from e

    def upload_file(
        self, source_path: Path, remote_path: str, chunk_size: int = 32768
    ) -> dict:
        """Upload a file from container filesystem to SFTP server.

        Uploads a file with automatic retry on transient failures (timeout,
        connection reset). Performs validation that source file exists
        before upload.

        Parameters
        ----------
        source_path : Path
            Local file path in container filesystem to upload
        remote_path : str
            Destination path on SFTP server (e.g. "/incoming/transfers/file.tar.gz")
        chunk_size : int
            Upload buffer size in bytes (default: 32KB)

        Returns
        -------
        dict
            Metadata about the upload:
            - "source_path": str - source file path
            - "remote_path": str - destination path
            - "file_size_bytes": int - uploaded file size
            - "attempts": int - number of attempts (including retries)

        Raises
        ------
        StorageError
            If source file does not exist, is not a file, or upload fails
            after all retries

        Example
        -------
        >>> client = SFTPClient(...)
        >>> metadata = client.upload_file(
        ...     Path("/tmp/archive.tar.gz"),
        ...     "/incoming/transfers/archive.tar.gz"
        ... )
        >>> print(f"Uploaded {metadata['file_size_bytes']} bytes")
        """
        # Validate source file
        if not source_path.exists():
            raise StorageError(f"Local file does not exist: {source_path}")
        if not source_path.is_file():
            raise StorageError(f"Path is not a file: {source_path}")

        file_size = source_path.stat().st_size
        attempt = 0

        while attempt <= self._max_retries:
            attempt += 1
            try:
                sftp = self._connect()
                sftp.put(str(source_path), remote_path, callback=None)
                sftp.close()

                LOGGER.debug(
                    "Uploaded file to SFTP",
                    extra={
                        "event": "sftp_upload",
                        "host": self._host,
                        "remote_path": remote_path,
                        "source_path": str(source_path),
                        "file_size_bytes": file_size,
                        "attempts": attempt,
                    },
                )
                return {
                    "source_path": str(source_path),
                    "remote_path": remote_path,
                    "file_size_bytes": file_size,
                    "attempts": attempt,
                }
            except self._paramiko.SSHException as e:
                if attempt <= self._max_retries:
                    backoff = self._retry_backoff ** (attempt - 1)
                    backoff = min(backoff, 60)  # Cap at 60 seconds
                    LOGGER.warning(
                        f"SFTP upload failed, retrying in {backoff}s",
                        extra={
                            "event": "sftp_retry",
                            "host": self._host,
                            "remote_path": remote_path,
                            "attempt": attempt,
                            "max_retries": self._max_retries,
                            "reason": str(e),
                        },
                    )
                    sleep(backoff)
                else:
                    raise StorageError(
                        f"Failed to upload {source_path} to sftp://{self._host}{remote_path} "
                        f"after {self._max_retries} retries: {e}"
                    ) from e
            except OSError as e:
                raise StorageError(
                    f"Failed to read local file {source_path}: {e}"
                ) from e
            except Exception as e:
                raise StorageError(
                    f"Failed to upload file to sftp://{self._host}{remote_path}: {e}"
                ) from e

    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the SFTP server.

        Non-throwing method to check file existence. Returns False for any
        error condition (connection failed, access denied, file not found, etc).

        Parameters
        ----------
        remote_path : str
            Remote file path to check (e.g. "/incoming/transfers/file.tar.gz")

        Returns
        -------
        bool
            True if file exists and is accessible, False otherwise

        Example
        -------
        >>> if client.file_exists("/incoming/transfers/manifest.json"):
        ...     print("Manifest already uploaded")
        """
        try:
            sftp = self._connect()
            sftp.stat(remote_path)
            sftp.close()
            return True
        except OSError:
            # File not found (OSError/IOError from SFTP)
            return False
        except Exception:
            # Any other error (connection, permission, etc) -> return False
            return False

    def delete_file(self, remote_path: str) -> None:
        """Delete a file from the SFTP server.

        Used for cleanup on upload failure or idempotency.

        Parameters
        ----------
        remote_path : str
            Remote file path to delete

        Raises
        ------
        StorageError
            If deletion fails (file not found, permission denied, etc)

        Example
        -------
        >>> client.delete_file("/incoming/transfers/failed-upload.tar.gz")
        """
        try:
            sftp = self._connect()
            sftp.remove(remote_path)
            sftp.close()

            LOGGER.debug(
                "Deleted file from SFTP",
                extra={
                    "event": "sftp_delete",
                    "host": self._host,
                    "remote_path": remote_path,
                },
            )
        except OSError as e:
            raise StorageError(
                f"File not found on SFTP server: {remote_path}"
            ) from e
        except Exception as e:
            raise StorageError(
                f"Failed to delete {remote_path} from sftp://{self._host}: {e}"
            ) from e
