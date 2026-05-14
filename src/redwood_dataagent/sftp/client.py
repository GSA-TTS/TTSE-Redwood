"""SFTP client wrapper for paramiko SSH/SFTP operations.

Provides a high-level interface for uploading files to SFTP endpoints with
automatic retry logic, connection pooling, multi-endpoint failover support,
and exception translation.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from time import sleep
from typing import Optional

from redwood_dataagent.exceptions import SFTPError
from redwood_dataagent.logging_utils import get_logger

LOGGER = get_logger(__name__)

# Default chunk size for SFTP uploads (32 MB). Suitable for 10–50 GB files;
# smaller chunks reduce lost-progress on retry, larger chunks improve throughput.
_DEFAULT_SFTP_CHUNK_SIZE_MB = 32
# Default connection/socket timeout in seconds for large-file transfers.
_DEFAULT_SFTP_TIMEOUT = 60
# Default max retry attempts for transient SFTP failures.
_DEFAULT_SFTP_MAX_RETRIES = 5


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
        "Invalid environment value for SFTP tuning; using default",
        extra={"event": "sftp_env_invalid", "name": name, "value": raw_value, "default": default},
    )
    return default


class SFTPClient:
    """SFTP client wrapper with multi-endpoint failover support.

    Handles SSH/SFTP connections to remote servers with support for:
    - Multiple endpoints (IP addresses or DNS names) with automatic failover
    - Key-based authentication using either file paths or key content
    - Connection retry with exponential backoff on transient failures
    - Comprehensive error translation and logging

    Parameters
    ----------
    hosts : list[str]
        List of SFTP endpoint hostnames or IP addresses. Connection attempts
        will be tried in order until one succeeds.
        Examples: ``["10.0.1.50", "10.0.2.50", "10.0.3.50"]`` or
        ``["sftp.example.com"]`` or ``["sftp-1.example.com", "sftp-2.example.com"]``
    username : str
        SSH username for authentication
    key_content : Optional[str]
        SSH private key content (as string). Either this or key_path must
        be provided. Useful when loading key from Secrets Manager.
    key_path : Optional[Path]
        Path to SSH private key file. Either this or key_content must
        be provided. Takes precedence over key_content if both provided.
    password : Optional[str]
        SSH password (if using password auth instead of key).
        If both password and key are provided, key takes precedence.
    port : int
        SSH/SFTP port (default: 22)
    timeout : int
        Connection and socket timeout in seconds (default: env ``SFTP_TIMEOUT``, else 60).
        Applied both at connect time and as a socket-level timeout to prevent
        silent stalls during large-file uploads.
    max_retries : int
        Maximum retry attempts on transient failures
        (default: env ``SFTP_MAX_RETRIES``, else 5).
    retry_backoff : float
        Base backoff multiplier for exponential retry (default: 2.0)
    chunk_size_mb : int
        Upload chunk size in MB used for streamed writes (default: env
        ``SFTP_CHUNK_SIZE_MB``, else 32). Larger values improve throughput;
        smaller values reduce data re-sent on retry.

    Raises
    ------
    SFTPError
        If paramiko is not installed, hosts list is empty, or authentication
        credentials are not provided correctly

    Example
    -------
    >>> # Using multiple IPs with key from Secrets Manager
    >>> client = SFTPClient(
    ...     hosts=["10.0.1.50", "10.0.2.50", "10.0.3.50"],
    ...     username="sender",
    ...     key_content=secret_key_material
    ... )
    >>> client.upload_file(
    ...     Path("/tmp/archive.tar.gz"),
    ...     "/outgoing/transfers/archive.tar.gz"
    ... )
    
    >>> # Using DNS with key file
    >>> client = SFTPClient(
    ...     hosts=["sftp.example.com"],
    ...     username="sender",
    ...     key_path=Path("/secrets/sender-key")
    ... )
    """

    def __init__(
        self,
        hosts: list[str],
        username: str,
        key_content: Optional[str] = None,
        key_path: Optional[Path] = None,
        password: Optional[str] = None,
        port: int = 22,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_backoff: float = 2.0,
        chunk_size_mb: Optional[int] = None,
    ) -> None:
        """Initialize SFTP client with multi-endpoint support."""
        # Lazy import for testing flexibility
        try:
            import paramiko
            self._paramiko = paramiko
        except ImportError as e:
            raise ImportError(
                "paramiko is required for SFTP support. "
                "Install with: pip install paramiko"
            ) from e

        if not hosts:
            raise SFTPError("hosts list cannot be empty")

        # Resolve env-driven defaults so agencies can tune without code changes.
        resolved_timeout = timeout if timeout is not None else _get_positive_int_env("SFTP_TIMEOUT", _DEFAULT_SFTP_TIMEOUT)
        resolved_max_retries = max_retries if max_retries is not None else _get_positive_int_env("SFTP_MAX_RETRIES", _DEFAULT_SFTP_MAX_RETRIES)
        resolved_chunk_size_mb = chunk_size_mb if chunk_size_mb is not None else _get_positive_int_env("SFTP_CHUNK_SIZE_MB", _DEFAULT_SFTP_CHUNK_SIZE_MB)

        self._hosts = hosts
        self._port = port
        self._username = username
        self._password = password
        self._key_path = key_path
        self._key_content = key_content
        self._timeout = resolved_timeout
        self._max_retries = resolved_max_retries
        self._retry_backoff = retry_backoff
        self._chunk_size = resolved_chunk_size_mb * 1024 * 1024
        self._transport = None
        self._connected_host = None

        # Validate authentication method (key or password required)
        if password is None and key_path is None and key_content is None:
            raise SFTPError(
                "Either password, key_path, or key_content must be provided "
                "for SFTP authentication"
            )

        # If key_path is provided, validate it exists
        if key_path is not None and not key_path.exists():
            raise SFTPError(f"SSH key file does not exist: {key_path}")

        LOGGER.debug(
            "SFTP client initialized",
            extra={
                "event": "sftp_init",
                "hosts": hosts,
                "port": port,
                "username": username,
                "auth_method": (
                    "key" if (key_path or key_content) else "password"
                ),
                "num_endpoints": len(hosts),
                "timeout_seconds": self._timeout,
                "max_retries": self._max_retries,
                "chunk_size_mb": resolved_chunk_size_mb,
            },
        )

    def _load_private_key_from_content(self, key_content: str):
        """Load private key from string content by trying supported key types."""
        key_file = io.StringIO(key_content)
        key_classes = [
            self._paramiko.RSAKey,
            self._paramiko.Ed25519Key,
            self._paramiko.ECDSAKey,
        ]

        dss_key_class = getattr(self._paramiko, "DSSKey", None)
        if dss_key_class is not None:
            key_classes.append(dss_key_class)

        for key_class in key_classes:
            try:
                return key_class.from_private_key(key_file)
            except (self._paramiko.SSHException, ValueError):
                key_file.seek(0)

        raise SFTPError(
            "Could not load private key - unsupported format or invalid key"
        )

    def _connect(self) -> paramiko.SFTPClient:
        """Create and return an SFTP client connection with multi-endpoint failover.

        Attempts connection to each host in the hosts list sequentially until
        one succeeds. Returns the first successful connection.
        Authentication failures are treated as credential issues and fail fast
        without trying additional endpoints.

        Returns
        -------
        paramiko.SFTPClient
            Connected SFTP client instance

        Raises
        ------
        SFTPError
            If connection fails to all endpoints (auth error, network issue, etc.)
        """
        last_error = None
        self._connected_host = None
        
        for host in self._hosts:
            try:
                ssh = self._paramiko.SSHClient()
                # Accept unknown host keys so first-time connections from
                # ephemeral pods do not fail due to missing known_hosts.
                ssh.set_missing_host_key_policy(
                    self._paramiko.AutoAddPolicy()
                )

                # key_path is still supported for backward compatibility and
                # local/container runs where SSH keys are mounted as files.
                # Determine auth method: key_path > key_content > password
                if self._key_path:
                    ssh.connect(
                        host,
                        port=self._port,
                        username=self._username,
                        key_filename=str(self._key_path),
                        timeout=self._timeout,
                    )
                elif self._key_content:
                    # Load key from content (e.g., from Secrets Manager)
                    private_key = self._load_private_key_from_content(
                        self._key_content
                    )

                    ssh.connect(
                        host,
                        port=self._port,
                        username=self._username,
                        pkey=private_key,
                        timeout=self._timeout,
                    )
                else:
                    # Fall back to password
                    ssh.connect(
                        host,
                        port=self._port,
                        username=self._username,
                        password=self._password,
                        timeout=self._timeout,
                    )

                # Apply socket-level timeout so large-file stalls
                # are detected and trigger a retry instead of hanging.
                transport = ssh.get_transport()
                if transport is not None:
                    transport.set_keepalive(30)  # send keepalive every 30s
                    sock = transport.sock
                    if sock is not None:
                        try:
                            sock.settimeout(self._timeout)
                        except OSError:
                            pass  # best-effort; may not apply on all platforms

                sftp = ssh.open_sftp()
                LOGGER.debug(
                    "Successfully connected to SFTP endpoint",
                    extra={
                        "event": "sftp_connect",
                        "host": host,
                        "port": self._port,
                    },
                )
                self._connected_host = host
                return sftp
                
            except self._paramiko.AuthenticationException as e:
                LOGGER.warning(
                    "SFTP authentication failed",
                    extra={
                        "event": "sftp_auth_failed",
                        "host": host,
                        "error": str(e),
                    },
                )
                raise SFTPError(
                    f"SFTP authentication failed for {self._username}@{host}. "
                    "Check credentials in Secrets Manager."
                ) from e
            except self._paramiko.SSHException as e:
                last_error = SFTPError(
                    f"SSH connection failed to {host}:{self._port}: {e}"
                )
                LOGGER.warning(
                    "SSH connection failed, trying next endpoint",
                    extra={
                        "event": "sftp_connect_failed",
                        "host": host,
                        "error": str(e),
                    },
                )
            except OSError as e:
                last_error = SFTPError(
                    f"Network error connecting to {host}:{self._port}: {e}"
                )
                LOGGER.warning(
                    "Network error, trying next endpoint",
                    extra={
                        "event": "sftp_network_error",
                        "host": host,
                        "error": str(e),
                    },
                )
            except Exception as e:
                last_error = SFTPError(
                    f"Failed to connect to SFTP server {host}: {e}"
                )
                LOGGER.warning(
                    "Unexpected error, trying next endpoint",
                    extra={
                        "event": "sftp_unexpected_error",
                        "host": host,
                        "error": str(e),
                    },
                )
        
        # All endpoints failed
        raise SFTPError(
            f"Failed to connect to any SFTP endpoint. "
            f"Tried {len(self._hosts)} hosts: {', '.join(self._hosts)}. "
            f"Last error: {last_error}"
        ) from last_error

    def upload_file(
        self, source_path: Path, remote_path: str
    ) -> dict:
        """Upload a file from container filesystem to SFTP server.

        Uploads a file with automatic retry on transient failures (timeout,
        connection reset) and failover to alternate endpoints. Performs validation
        that source file exists before upload.

        Uses chunked streaming via ``sftp.open()`` with the configured
        ``chunk_size_mb`` so large files (10–50 GB) do not require buffering
        the entire file in memory and stall timeouts are detected per chunk.

        Parameters
        ----------
        source_path : Path
            Local file path in container filesystem to upload
        remote_path : str
            Destination path on SFTP server (e.g. "/outgoing/transfers/file.tar.gz")

        Returns
        -------
        dict
            Metadata about the upload:
            - "source_path": str - source file path
            - "remote_path": str - destination path
            - "file_size_bytes": int - uploaded file size
            - "attempts": int - number of attempts (including retries)
            - "endpoint": str - endpoint that succeeded

        Raises
        ------
        SFTPError
            If source file does not exist, is not a file, or upload fails
            after all retries on all endpoints

        Example
        -------
        >>> client = SFTPClient(...)
        >>> metadata = client.upload_file(
        ...     Path("/tmp/archive.tar.gz"),
        ...     "/outgoing/transfers/archive.tar.gz"
        ... )
        >>> print(
        ...     f"Uploaded {metadata['file_size_bytes']} bytes to {metadata['endpoint']}"
        ... )
        """
        self._validate_upload_source(source_path)

        file_size = source_path.stat().st_size
        attempt = 0
        connected_host = None

        while attempt <= self._max_retries:
            attempt += 1
            try:
                sftp = self._connect()
                connected_host = self._connected_host or self._hosts[0]

                # Stream upload in configurable chunks so large files do not
                # buffer fully in memory and per-chunk timeouts are enforced.
                with open(source_path, "rb") as local_fh:
                    with sftp.open(remote_path, "wb") as remote_fh:
                        remote_fh.set_pipelined(True)
                        while True:
                            chunk = local_fh.read(self._chunk_size)
                            if not chunk:
                                break
                            remote_fh.write(chunk)

                sftp.close()

                LOGGER.debug(
                    "Uploaded file to SFTP",
                    extra={
                        "event": "sftp_upload",
                        "endpoint": connected_host,
                        "remote_path": remote_path,
                        "source_path": str(source_path),
                        "file_size_bytes": file_size,
                        "chunk_size_bytes": self._chunk_size,
                        "attempts": attempt,
                    },
                )
                return {
                    "source_path": str(source_path),
                    "remote_path": remote_path,
                    "file_size_bytes": file_size,
                    "attempts": attempt,
                    "endpoint": connected_host,
                }
            except self._paramiko.SSHException as e:
                if attempt <= self._max_retries:
                    backoff = self._retry_backoff ** (attempt - 1)
                    backoff = min(backoff, 60)  # Cap at 60 seconds
                    LOGGER.warning(
                        f"SFTP upload failed, retrying in {backoff}s",
                        extra={
                            "event": "sftp_retry",
                            "remote_path": remote_path,
                            "attempt": attempt,
                            "max_retries": self._max_retries,
                            "reason": str(e),
                        },
                    )
                    sleep(backoff)
                else:
                    raise SFTPError(
                        f"Failed to upload {source_path} to sftp://{connected_host or '(all endpoints)'}{remote_path} "
                        f"after {self._max_retries} retries: {e}"
                    ) from e
            except OSError as e:
                raise SFTPError(
                    f"Failed to read local file {source_path}: {e}"
                ) from e
            except Exception as e:
                raise SFTPError(
                    f"Failed to upload file to sftp://{connected_host or '(all endpoints)'}{remote_path}: {e}"
                ) from e

    def _validate_upload_source(self, source_path: Path) -> None:
        """Validate upload source path points to an existing file."""
        # Validate source file
        if not source_path.exists():
            raise SFTPError(f"Local file does not exist: {source_path}")
        if not source_path.is_file():
            raise SFTPError(f"Path is not a file: {source_path}")

    def file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on the SFTP server.

        Non-throwing method to check file existence. Returns False for any
        error condition (connection failed, access denied, file not found, etc).
        Tries all endpoints before failing.

        Parameters
        ----------
        remote_path : str
            Remote file path to check (e.g. "/outgoing/transfers/file.tar.gz")

        Returns
        -------
        bool
            True if file exists and is accessible on any endpoint, False otherwise

        Example
        -------
        >>> if client.file_exists("/outgoing/transfers/manifest.json"):
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

        Used for cleanup on upload failure or idempotency. Attempts connection
        to all endpoints until one succeeds.

        Parameters
        ----------
        remote_path : str
            Remote file path to delete

        Raises
        ------
        SFTPError
            If deletion fails (file not found, permission denied, connection
            failed to all endpoints, etc)

        Example
        -------
        >>> client.delete_file("/outgoing/transfers/failed-upload.tar.gz")
        """
        try:
            sftp = self._connect()
            sftp.remove(remote_path)
            sftp.close()

            LOGGER.debug(
                "Deleted file from SFTP",
                extra={
                    "event": "sftp_delete",
                    "remote_path": remote_path,
                },
            )
        except OSError as e:
            raise SFTPError(
                f"File not found on SFTP server: {remote_path}"
            ) from e
        except Exception as e:
            raise SFTPError(
                f"Failed to delete {remote_path} from SFTP server: {e}"
            ) from e
