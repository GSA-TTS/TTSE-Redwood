"""Tests for SFTP client factory functions."""

from __future__ import annotations

import pytest

from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.sftp.factory import create_sftp_client_from_credentials


class TestCreateSFTPClientFromCredentials:
    """Tests for create_sftp_client_from_credentials factory function."""

    def test_create_client_success(self):
        """Test successful SFTP client creation from direct credentials."""
        client = create_sftp_client_from_credentials(
            sftp_endpoints=["10.0.1.50", "10.0.2.50"],
            username="dot-sender",
            private_key_content="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
        )

        assert client._hosts == ["10.0.1.50", "10.0.2.50"]
        assert client._username == "dot-sender"
        assert "BEGIN OPENSSH PRIVATE KEY" in client._key_content

    def test_create_client_custom_parameters(self):
        """Test SFTP client creation with custom transport parameters."""
        client = create_sftp_client_from_credentials(
            sftp_endpoints=["sftp.example.com"],
            username="dot-sender",
            private_key_content="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
            port=2222,
            timeout=60,
            max_retries=5,
            retry_backoff=1.5,
        )

        assert client._port == 2222
        assert client._timeout == 60
        assert client._max_retries == 5
        assert client._retry_backoff == 1.5

    def test_create_client_invalid_username_type(self):
        """Test creation fails when username is not a string."""
        with pytest.raises(StorageError, match="Invalid SFTP username value"):
            create_sftp_client_from_credentials(
                sftp_endpoints=["10.0.1.50"],
                username=123,  # type: ignore[arg-type]
                private_key_content="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
            )

    def test_create_client_blank_username(self):
        """Test creation fails when username is empty/blank."""
        with pytest.raises(StorageError, match="Invalid SFTP username value"):
            create_sftp_client_from_credentials(
                sftp_endpoints=["10.0.1.50"],
                username="  ",
                private_key_content="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
            )

    def test_create_client_blank_private_key(self):
        """Test creation fails when private key is empty."""
        with pytest.raises(StorageError, match="Invalid SFTP private key value"):
            create_sftp_client_from_credentials(
                sftp_endpoints=["10.0.1.50"],
                username="dot-sender",
                private_key_content="",
            )

    def test_create_client_invalid_private_key_type(self):
        """Test creation fails when private key is not a string."""
        with pytest.raises(StorageError, match="Invalid SFTP private key value"):
            create_sftp_client_from_credentials(
                sftp_endpoints=["10.0.1.50"],
                username="dot-sender",
                private_key_content=123,  # type: ignore[arg-type]
            )

    def test_create_client_multiple_endpoints(self):
        """Test SFTP client creation with multiple endpoints."""
        endpoints = ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        client = create_sftp_client_from_credentials(
            sftp_endpoints=endpoints,
            username="dot-sender",
            private_key_content="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
        )

        assert client._hosts == endpoints
