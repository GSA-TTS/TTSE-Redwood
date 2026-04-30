"""Tests for SFTP client factory functions."""

from __future__ import annotations

from unittest import mock

import pytest

from redwood_dataagent.exceptions import SecretsManagerError, StorageError
from redwood_dataagent.sftp.factory import create_sftp_client_from_secrets_manager


class TestCreateSFTPClientFromSecretsManager:
    """Tests for create_sftp_client_from_secrets_manager factory function."""

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_success(self, mock_secrets_class):
        """Test successful SFTP client creation from Secrets Manager."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "sftp_user",
            "private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
            "public-key": "ssh-rsa AAAA..."
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        client = create_sftp_client_from_secrets_manager(
            sftp_endpoints=["10.0.1.50", "10.0.2.50"],
            secrets_manager_name="tts-core-dev-redwood-sftp-credentials",
            aws_region="us-east-1",
        )

        # Verify secrets client was created
        mock_secrets_class.assert_called_once_with(aws_region="us-east-1")
        
        # Verify secret was retrieved
        mock_secrets_client.get_json_secret.assert_called_once_with(
            "tts-core-dev-redwood-sftp-credentials"
        )
        
        # Verify SFTP client was created with correct parameters
        assert client._hosts == ["10.0.1.50", "10.0.2.50"]
        assert client._username == "sftp_user"
        assert "-----BEGIN RSA PRIVATE KEY-----" in client._key_content

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_custom_parameters(self, mock_secrets_class):
        """Test SFTP client creation with custom parameters."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "sftp_user",
            "private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        client = create_sftp_client_from_secrets_manager(
            sftp_endpoints=["sftp.example.com"],
            secrets_manager_name="custom-secret",
            aws_region="eu-west-1",
            port=2222,
            timeout=60,
            max_retries=5,
            retry_backoff=1.5,
        )

        assert client._port == 2222
        assert client._timeout == 60
        assert client._max_retries == 5
        assert client._retry_backoff == 1.5

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_missing_user_key(self, mock_secrets_class):
        """Test creation fails when secret missing 'user' key."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        with pytest.raises(StorageError, match="missing required keys"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="test-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_missing_private_key(self, mock_secrets_class):
        """Test creation fails when secret missing 'private-key' key."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "sftp_user",
            "public-key": "ssh-rsa AAAA..."
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        with pytest.raises(StorageError, match="missing required keys"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="test-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_invalid_user_type(self, mock_secrets_class):
        """Test creation fails when 'user' is not a string."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": 123,  # Invalid: should be string
            "private-key": "-----BEGIN RSA PRIVATE KEY-----"
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        with pytest.raises(StorageError, match="Invalid 'user' value"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="test-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_empty_user(self, mock_secrets_class):
        """Test creation fails when 'user' is empty."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "",  # Invalid: should be non-empty
            "private-key": "-----BEGIN RSA PRIVATE KEY-----"
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        with pytest.raises(StorageError, match="Invalid 'user' value"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="test-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_empty_private_key(self, mock_secrets_class):
        """Test creation fails when 'private-key' is empty."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "sftp_user",
            "private-key": ""  # Invalid: should be non-empty
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        with pytest.raises(StorageError, match="Invalid 'private-key' value"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="test-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_secrets_manager_error(self, mock_secrets_class):
        """Test creation fails when Secrets Manager raises error."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        mock_secrets_client.get_json_secret.side_effect = SecretsManagerError(
            "Secret not found"
        )

        with pytest.raises(SecretsManagerError, match="Secret not found"):
            create_sftp_client_from_secrets_manager(
                sftp_endpoints=["10.0.1.50"],
                secrets_manager_name="nonexistent-secret",
                aws_region="us-east-1",
            )

    @mock.patch("redwood_dataagent.sftp.factory.SecretsManagerClient")
    def test_create_client_multiple_endpoints(self, mock_secrets_class):
        """Test SFTP client creation with multiple endpoints."""
        mock_secrets_client = mock.MagicMock()
        mock_secrets_class.return_value = mock_secrets_client
        
        secret_data = {
            "user": "sftp_user",
            "private-key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
        }
        mock_secrets_client.get_json_secret.return_value = secret_data

        endpoints = ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        client = create_sftp_client_from_secrets_manager(
            sftp_endpoints=endpoints,
            secrets_manager_name="test-secret",
            aws_region="us-east-1",
        )

        assert client._hosts == endpoints
