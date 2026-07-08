"""Helper to create SFTP clients using environment-injected credentials."""

from __future__ import annotations

from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.logging_utils import get_logger

from .client import SFTPClient

LOGGER = get_logger(__name__)


def create_sftp_client_from_credentials(
    sftp_endpoints: list[str],
    username: str,
    private_key_content: str,
    port: int = 22,
    timeout: int = 30,
    max_retries: int = 3,
    retry_backoff: float = 2.0,
) -> SFTPClient:
    """Create an SFTP client with credentials already available in memory.

    Parameters
    ----------
    sftp_endpoints : list[str]
        List of SFTP servers (can be IPs or DNS names, single or multiple).
        Examples: ["10.0.1.50"] or ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        or ["sftp.example.com"] or ["sftp-1.example.com", "sftp-2.example.com"]
    username : str
        SFTP username.
    private_key_content : str
        OpenSSH private key content.
    port : int
        SFTP port. Default: 22
    timeout : int
        Connection timeout in seconds. Default: 30
    max_retries : int
        How many times to retry if connection fails. Default: 3
    retry_backoff : float
        Wait time multiplier between retries. Default: 2.0

    Returns
    -------
    SFTPClient
        Ready-to-use SFTP client for uploading files

    Raises
    ------
    StorageError
        If secret format is invalid or required fields are missing
    StorageError
        If required credential values are missing/invalid

    Example
    -------
    >>> from redwood_dataagent.config import load_config
    >>> config = load_config()
    >>> client = create_sftp_client_from_credentials(
    ...     sftp_endpoints=config.sftp_endpoints,
    ...     username=config.sftp_username,
    ...     private_key_content=config.sftp_private_key,
    ... )
    >>> client.upload_file(Path("myfile.tar.gz"), "/outgoing/myfile.tar.gz")
    """
    # Validate username is a non-empty string
    if not isinstance(username, str) or not username.strip():
        raise StorageError("Invalid SFTP username value: " f"expected non-empty string, got {type(username).__name__}")

    # Validate private key is a non-empty string
    if not isinstance(private_key_content, str) or not private_key_content.strip():
        raise StorageError(
            "Invalid SFTP private key value: " f"expected non-empty string, got {type(private_key_content).__name__}"
        )

    # Log what we're doing (for debugging/monitoring)
    LOGGER.debug(
        "Creating SFTP client from environment credentials",
        extra={
            "event": "sftp_client_creation",
            "num_endpoints": len(sftp_endpoints),
            "endpoints": sftp_endpoints,
            "username": username,
        },
    )

    # Create and return the SFTP client
    return SFTPClient(
        hosts=sftp_endpoints,
        username=username,
        key_content=private_key_content,
        port=port,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
