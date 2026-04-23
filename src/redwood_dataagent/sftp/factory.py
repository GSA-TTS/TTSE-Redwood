"""Helper to create SFTP clients using AWS Secrets Manager credentials.

This module provides a simple way to set up an SFTP client by automatically
fetching credentials (username and private key) from AWS Secrets Manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from redwood_dataagent.aws.secrets_manager import SecretsManagerClient
from redwood_dataagent.exceptions import SecretsManagerError, StorageError
from redwood_dataagent.logging_utils import get_logger

from .client import SFTPClient

LOGGER = get_logger(__name__)


def create_sftp_client_from_secrets_manager(
    sftp_endpoints: list[str],
    secrets_manager_name: str,
    aws_region: str,
    port: int = 22,
    timeout: int = 30,
    max_retries: int = 3,
    retry_backoff: float = 2.0,
) -> SFTPClient:
    """Create an SFTP client with credentials from AWS Secrets Manager.

    This function:
    1. Fetches credentials (username + private key) from Secrets Manager
    2. Validates the credentials are valid
    3. Creates and returns an SFTP client ready to upload files

    Required secret format (JSON):
    {
      "user": "username",
      "private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
    }

    Parameters
    ----------
    sftp_endpoints : list[str]
        List of SFTP servers (can be IPs or DNS names, single or multiple).
        Examples: ["10.0.1.50"] or ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        or ["sftp.example.com"] or ["sftp-1.example.com", "sftp-2.example.com"]
    secrets_manager_name : str
        Name of the secret in AWS Secrets Manager
    aws_region : str
        AWS region (passed from helm chart AWS_REGION environment variable)
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
    SecretsManagerError
        If Secrets Manager lookup fails

    Example
    -------
    >>> from redwood_dataagent.config import load_config
    >>> config = load_config()
    >>> client = create_sftp_client_from_secrets_manager(
    ...     sftp_endpoints=config.sftp_endpoints,
    ...     secrets_manager_name=config.sftp_secrets_manager_name,
    ...     aws_region=config.aws_region
    ... )
    >>> client.upload_file(Path("myfile.tar.gz"), "/incoming/myfile.tar.gz")
    """
    # Step 1: Connect to Secrets Manager and get credentials
    secrets_client = SecretsManagerClient(aws_region=aws_region)
    secret_dict = secrets_client.get_json_secret(secrets_manager_name)

    # Step 2: Check that the secret has the required fields
    required_keys = {"user", "private-key"}
    missing_keys = required_keys - set(secret_dict.keys())
    if missing_keys:
        raise StorageError(
            f"Secret '{secrets_manager_name}' is missing required keys: "
            f"{', '.join(sorted(missing_keys))}"
        )

    # Step 3: Extract username and private key
    username = secret_dict.get("user")
    private_key_content = secret_dict.get("private-key")

    # Step 4: Validate username is a non-empty string
    if not isinstance(username, str) or not username.strip():
        raise StorageError(
            f"Invalid 'user' value in secret '{secrets_manager_name}': "
            f"expected non-empty string, got {type(username).__name__}"
        )

    # Step 5: Validate private key is a non-empty string
    if not isinstance(private_key_content, str) or not private_key_content.strip():
        raise StorageError(
            f"Invalid 'private-key' value in secret '{secrets_manager_name}': "
            f"expected non-empty string, got {type(private_key_content).__name__}"
        )

    # Log what we're doing (for debugging/monitoring)
    LOGGER.debug(
        "Creating SFTP client from Secrets Manager credentials",
        extra={
            "event": "sftp_client_creation",
            "secret_name": secrets_manager_name,
            "num_endpoints": len(sftp_endpoints),
            "endpoints": sftp_endpoints,
            "username": username,
        },
    )

    # Step 6: Create and return the SFTP client
    return SFTPClient(
        hosts=sftp_endpoints,
        username=username,
        key_content=private_key_content,
        port=port,
        timeout=timeout,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )
