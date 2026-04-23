"""Tests for AWS Secrets Manager client utilities."""

from __future__ import annotations

from unittest import mock

import pytest

from redwood_dataagent.aws.secrets_manager import SecretsManagerClient
from redwood_dataagent.exceptions import SecretsManagerError


def _attach_secrets_manager_exception_types(mock_client: mock.MagicMock) -> None:
    """Attach boto-like exception classes to a mocked Secrets Manager client."""
    mock_client.exceptions = mock.MagicMock()
    mock_client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    mock_client.exceptions.InvalidRequestException = type(
        "InvalidRequestException", (Exception,), {}
    )
    mock_client.exceptions.InvalidParameterException = type(
        "InvalidParameterException", (Exception,), {}
    )


class TestSecretsManagerClientInit:
    """Tests for SecretsManagerClient initialization."""

    def test_init_default_region(self):
        """Test initialization with default AWS region."""
        with mock.patch("boto3.client"):
            client = SecretsManagerClient()
            assert client._region == "us-east-1"

    def test_init_custom_region(self):
        """Test initialization with custom AWS region."""
        with mock.patch("boto3.client"):
            client = SecretsManagerClient(aws_region="eu-west-1")
            assert client._region == "eu-west-1"

    def test_init_boto3_import_error(self):
        """Test initialization fails if boto3 not installed."""
        with mock.patch("boto3.client", side_effect=ImportError("No module")):
            with pytest.raises(ImportError, match="boto3 is required"):
                SecretsManagerClient()


class TestSecretsManagerClientGetJsonSecret:
    """Tests for SecretsManagerClient.get_json_secret method."""

    @mock.patch("boto3.client")
    def test_get_json_secret_success(self, mock_boto3_client):
        """Test successful retrieval of JSON secret."""
        mock_client = mock.MagicMock()
        _attach_secrets_manager_exception_types(mock_client)
        secret_content = '{"user": "sender", "private-key": "-----BEGIN RSA-----"}'
        mock_client.get_secret_value.return_value = {
            "SecretString": secret_content
        }
        mock_boto3_client.return_value = mock_client

        client = SecretsManagerClient()

        result = client.get_json_secret("tts-core-dev-redwood-sftp-credentials")

        assert result["user"] == "sender"
        assert result["private-key"] == "-----BEGIN RSA-----"

    @mock.patch("boto3.client")
    def test_get_json_secret_from_binary(self, mock_boto3_client):
        """Test retrieval of JSON secret from SecretBinary."""
        mock_client = mock.MagicMock()
        _attach_secrets_manager_exception_types(mock_client)
        secret_content = b'{"user": "sender", "private-key": "key"}'
        mock_client.get_secret_value.return_value = {
            "SecretBinary": secret_content
        }
        mock_boto3_client.return_value = mock_client

        client = SecretsManagerClient()

        result = client.get_json_secret("test-secret")

        assert result["user"] == "sender"

    @mock.patch("boto3.client")
    def test_get_json_secret_invalid_json(self, mock_boto3_client):
        """Test retrieval fails on invalid JSON."""
        mock_client = mock.MagicMock()
        _attach_secrets_manager_exception_types(mock_client)
        mock_client.get_secret_value.return_value = {
            "SecretString": "not valid json {"
        }
        mock_boto3_client.return_value = mock_client

        client = SecretsManagerClient()

        with pytest.raises(SecretsManagerError, match="not valid JSON"):
            client.get_json_secret("test-secret")

    @mock.patch("boto3.client")
    def test_get_json_secret_not_found(self, mock_boto3_client):
        """Test retrieval fails when secret not found."""
        mock_client = mock.MagicMock()
        _attach_secrets_manager_exception_types(mock_client)
        mock_boto3_client.return_value = mock_client

        client = SecretsManagerClient()

        mock_client.get_secret_value.side_effect = mock_client.exceptions.ResourceNotFoundException()

        with pytest.raises(SecretsManagerError, match="not found in Secrets Manager"):
            client.get_json_secret("nonexistent-secret")

    @mock.patch("boto3.client")
    def test_get_json_secret_generic_error(self, mock_boto3_client):
        """Test retrieval fails on generic error."""
        mock_client = mock.MagicMock()
        _attach_secrets_manager_exception_types(mock_client)
        mock_client.get_secret_value.side_effect = Exception("Some error")
        mock_boto3_client.return_value = mock_client

        client = SecretsManagerClient()

        with pytest.raises(SecretsManagerError, match="Failed to retrieve secret"):
            client.get_json_secret("test-secret")
