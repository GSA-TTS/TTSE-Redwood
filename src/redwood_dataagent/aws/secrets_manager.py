"""Helper to fetch secrets (like passwords and API keys) from AWS.

This module reads JSON secrets stored in AWS Secrets Manager.
"""

from __future__ import annotations

import json
from typing import Any

from ..exceptions import SecretsManagerError
from ..logging_utils import (
    get_logger,
    prefix_log_message,
)

LOGGER = get_logger("redwood_dataagent")


class SecretsManagerClient:
    """Fetch secrets from AWS (username, password, API keys, etc).

    Use this to retrieve credentials stored in AWS Secrets Manager.

    Parameters
    ----------
    aws_region : str
        AWS region where your secrets are stored. Default: "us-east-1"

    Raises
    ------
    ImportError
        If boto3 library is not installed

    Example
    -------
    >>> client = SecretsManagerClient(aws_region="us-east-1")
    >>> creds = client.get_json_secret("my-sftp-secret")
    >>> user = creds["user"]
    """

    def __init__(self, aws_region: str = "us-east-1") -> None:
        """Connect to AWS Secrets Manager in a specific region.

        Parameters
        ----------
        aws_region : str
            AWS region. Default: "us-east-1"

        Raises
        ------
        ImportError
            If boto3 library is not installed
        """
        try:
            import boto3
            # Create connection to AWS Secrets Manager
            self._client: Any = boto3.client(
                "secretsmanager", region_name=aws_region
            )
            self._region = aws_region
        except ImportError as e:
            raise ImportError(
                "boto3 is required for AWS Secrets Manager support. "
                "Install with: pip install boto3"
            ) from e

        # Log connection for debugging
        LOGGER.debug(
            prefix_log_message(
                "Secrets Manager client initialized",
            ),
            extra={
                "event": "secrets_manager_init",
                "region": aws_region,
            },
        )

    def get_json_secret(self, secret_name: str) -> dict[str, Any]:
        """Fetch a secret stored as JSON from AWS.

        Example secret format:
        {
          "user": "myuser",
          "password": "mypass",
          "private-key": "-----BEGIN RSA KEY-----..."
        }

        Parameters
        ----------
        secret_name : str
            Name of the secret in AWS (e.g., "my-sftp-secret")

        Returns
        -------
        dict
            The secret data as a dictionary

        Raises
        ------
        SecretsManagerError
            If secret not found, cannot be read, or not valid JSON

        Example
        -------
        >>> client = SecretsManagerClient()
        >>> creds = client.get_json_secret("my-sftp-secret")
        >>> print(creds["user"])
        """
        try:
            # Fetch secret from AWS
            response = self._client.get_secret_value(SecretId=secret_name)

            # Secret can come as text or binary - handle both
            if "SecretString" in response:
                secret_value = response["SecretString"]
            else:
                secret_value = response["SecretBinary"].decode("utf-8")

            # Parse and validate JSON
            try:
                secret_dict = json.loads(secret_value)
            except json.JSONDecodeError as e:
                raise SecretsManagerError(
                    f"Secret '{secret_name}' is not valid JSON: {e}"
                ) from e

            # Log what we retrieved (for debugging)
            LOGGER.debug(
                prefix_log_message(
                    "Retrieved secret from Secrets Manager",
                ),
                extra={
                    "event": "secret_retrieved",
                    "secret_name": secret_name,
                    "keys": list(secret_dict.keys()),
                    "key_count": len(secret_dict),
                },
            )

            return secret_dict
        except self._client.exceptions.ResourceNotFoundException as e:
            raise SecretsManagerError(
                f"Secret '{secret_name}' not found in Secrets Manager"
            ) from e
        except self._client.exceptions.InvalidRequestException as e:
            raise SecretsManagerError(
                f"Invalid request for secret '{secret_name}': {e}"
            ) from e
        except self._client.exceptions.InvalidParameterException as e:
            raise SecretsManagerError(
                f"Invalid parameters for secret '{secret_name}': {e}"
            ) from e
        except Exception as e:
            raise SecretsManagerError(
                f"Failed to retrieve secret '{secret_name}': {e}"
            ) from e
