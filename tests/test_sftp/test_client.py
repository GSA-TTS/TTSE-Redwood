"""Tests for SFTP client utilities."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from redwood_dataagent.exceptions import SFTPError
from redwood_dataagent.sftp.client import SFTPClient


class TestSFTPClientInit:
    """Tests for SFTPClient initialization and configuration."""

    def test_init_with_password(self):
        """Test initialization with password authentication."""
        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret-pass",
            port=2222,
            timeout=60,
        )

        assert client._hosts == ["receiver.example.com"]
        assert client._port == 2222
        assert client._username == "sender"
        assert client._password == "secret-pass"
        assert client._timeout == 60

    def test_init_with_multiple_hosts(self):
        """Test initialization with multiple hosts."""
        hosts = ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        client = SFTPClient(
            hosts=hosts,
            username="sender",
            password="secret-pass",
        )

        assert client._hosts == hosts

    def test_init_with_key(self, tmp_path):
        """Test initialization with key-based authentication."""
        key_file = tmp_path / "id_rsa"
        key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            key_path=key_file,
        )

        assert client._key_path == key_file
        assert client._password is None

    def test_init_with_key_content(self):
        """Test initialization with key content (from Secrets Manager)."""
        key_content = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            key_content=key_content,
        )

        assert client._key_content == key_content
        assert client._key_path is None
        assert client._password is None

    def test_init_no_auth_method_fails(self):
        """Test initialization fails when no auth method provided."""
        with pytest.raises(
            SFTPError,
            match="Either password, key_path, or key_content must be provided"
        ):
            SFTPClient(
                hosts=["receiver.example.com"],
                username="sender",
            )

    def test_init_empty_hosts_fails(self):
        """Test initialization fails when hosts list is empty."""
        with pytest.raises(SFTPError, match="hosts list cannot be empty"):
            SFTPClient(
                hosts=[],
                username="sender",
                password="secret",
            )

    def test_init_key_not_found_fails(self, tmp_path):
        """Test initialization fails when key file not found."""
        with pytest.raises(SFTPError, match="SSH key file does not exist"):
            SFTPClient(
                hosts=["receiver.example.com"],
                username="sender",
                key_path=tmp_path / "nonexistent.key",
            )


class TestSFTPClientUpload:
    """Tests for SFTPClient.upload_file method."""

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_success(self, mock_connect, tmp_path):
        """Test successful file upload."""
        mock_sftp = mock.MagicMock()
        mock_connect.return_value = mock_sftp

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )
        metadata = client.upload_file(source_file, "/incoming/archive.tar.gz")

        assert metadata["source_path"] == str(source_file)
        assert metadata["remote_path"] == "/incoming/archive.tar.gz"
        assert metadata["file_size_bytes"] == 7
        assert metadata["attempts"] == 1
        assert metadata["endpoint"] == "receiver.example.com"
        mock_sftp.put.assert_called_once()
        mock_sftp.close.assert_called_once()

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_to_multiple_hosts_endpoint_in_metadata(
        self, mock_connect, tmp_path
    ):
        """Test upload includes the actual connected endpoint in metadata."""
        mock_sftp = mock.MagicMock()

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        hosts = ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
        client = SFTPClient(
            hosts=hosts,
            username="sender",
            password="secret",
        )

        # Simulate _connect choosing the second endpoint.
        def _mock_connect_with_selected_host():
            client._connected_host = hosts[1]
            return mock_sftp

        mock_connect.side_effect = _mock_connect_with_selected_host

        metadata = client.upload_file(source_file, "/incoming/archive.tar.gz")

        assert metadata["endpoint"] == hosts[1]

    def test_upload_file_not_found(self):
        """Test upload fails when local file not found."""
        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Local file does not exist"):
            client.upload_file(Path("/nonexistent.tar.gz"), "/incoming/")

    def test_upload_dir_fails(self, tmp_path):
        """Test upload fails when source is directory."""
        source_dir = tmp_path / "mydir"
        source_dir.mkdir()

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Path is not a file"):
            client.upload_file(source_dir, "/incoming/")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_auth_error(self, mock_connect, tmp_path):
        """Test upload fails immediately on authentication error."""
        mock_connect.side_effect = SFTPError(
            "SFTP authentication failed for sender@receiver.example.com"
        )

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="wrong",
        )

        with pytest.raises(SFTPError, match="SFTP authentication failed"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")
        assert mock_connect.call_count == 1

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_ssh_error(self, mock_connect, tmp_path):
        """Test upload fails on SSH error."""
        import paramiko

        mock_connect.side_effect = paramiko.SSHException("connection lost")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="after .* retries"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_network_error(self, mock_connect, tmp_path):
        """Test upload fails on network error."""
        mock_connect.side_effect = OSError("Network unreachable")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Failed to read local file"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.sleep")
    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_with_retry(self, mock_connect, mock_sleep, tmp_path):
        """Test upload retries on transient failure."""
        import paramiko

        mock_sftp = mock.MagicMock()
        mock_connect.side_effect = [
            paramiko.SSHException("timeout"),
            mock_sftp,
        ]

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
            max_retries=1,
            retry_backoff=0.1,
        )

        metadata = client.upload_file(source_file, "/incoming/archive.tar.gz")
        assert metadata["attempts"] == 2
        mock_sleep.assert_called_once()

    @mock.patch("redwood_dataagent.sftp.client.sleep")
    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_max_retries(self, mock_connect, mock_sleep, tmp_path):
        """Test upload fails after max retries exceeded."""
        import paramiko

        mock_connect.side_effect = paramiko.SSHException("timeout")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
            max_retries=2,
            retry_backoff=0.1,
        )

        with pytest.raises(SFTPError, match="after .* retries"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")


class TestSFTPClientFileExists:
    """Tests for SFTPClient.file_exists method."""

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_file_exists_true(self, mock_connect):
        """Test file_exists returns True when file found."""
        mock_sftp = mock.MagicMock()
        mock_sftp.stat.return_value = mock.MagicMock()
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )
        exists = client.file_exists("/incoming/manifest.json")

        assert exists is True

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_file_exists_false_not_found(self, mock_connect):
        """Test file_exists returns False when file not found."""
        mock_sftp = mock.MagicMock()
        mock_sftp.stat.side_effect = OSError("No such file")
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )
        exists = client.file_exists("/incoming/nonexistent.json")

        assert exists is False

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_file_exists_false_on_error(self, mock_connect):
        """Test file_exists returns False on any error."""
        mock_connect.side_effect = Exception("connection error")

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )
        exists = client.file_exists("/incoming/manifest.json")

        assert exists is False


class TestSFTPClientDelete:
    """Tests for SFTPClient.delete_file method."""

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_delete_success(self, mock_connect):
        """Test successful file deletion."""
        mock_sftp = mock.MagicMock()
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )
        client.delete_file("/incoming/failed-upload.tar.gz")

        mock_sftp.remove.assert_called_once_with(
            "/incoming/failed-upload.tar.gz"
        )

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_delete_not_found(self, mock_connect):
        """Test delete fails when file not found."""
        mock_sftp = mock.MagicMock()
        mock_sftp.remove.side_effect = OSError("No such file")
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="File not found"):
            client.delete_file("/incoming/nonexistent.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_delete_error(self, mock_connect):
        """Test delete fails on generic error."""
        mock_sftp = mock.MagicMock()
        mock_sftp.remove.side_effect = Exception("permission denied")
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            hosts=["receiver.example.com"],
            username="sender",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Failed to delete"):
            client.delete_file("/incoming/file.tar.gz")


class TestSFTPClientConnect:
    """Tests for SFTPClient._connect method with real paramiko interactions."""

    @mock.patch("paramiko.SSHClient")
    def test_connect_with_password_auth(self, mock_ssh_class):
        """Test _connect with password authentication."""
        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            password="testpass",
            port=2222,
            timeout=45,
        )

        result = client._connect()

        assert result == mock_sftp
        assert client._connected_host == "server.example.com"
        mock_ssh.set_missing_host_key_policy.assert_called_once()
        # Verify password auth was used
        mock_ssh.connect.assert_called_once_with(
            "server.example.com",
            port=2222,
            username="testuser",
            password="testpass",
            timeout=45,
        )

    @mock.patch("paramiko.SSHClient")
    def test_connect_with_key_file(self, mock_ssh_class, tmp_path):
        """Test _connect with key file authentication."""
        key_file = tmp_path / "id_rsa"
        key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")

        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            key_path=key_file,
            port=2222,
        )

        result = client._connect()

        assert result == mock_sftp
        # Verify key auth was used
        mock_ssh.connect.assert_called_once_with(
            "server.example.com",
            port=2222,
            username="testuser",
            key_filename=str(key_file),
            timeout=30,
        )

    @mock.patch("paramiko.RSAKey")
    @mock.patch("paramiko.SSHClient")
    def test_connect_with_key_content(self, mock_ssh_class, mock_rsa_key):
        """Test _connect with key content (from Secrets Manager)."""
        key_content = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
        mock_key_instance = mock.MagicMock()
        mock_rsa_key.from_private_key.return_value = mock_key_instance

        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            key_content=key_content,
        )

        result = client._connect()

        assert result == mock_sftp
        mock_ssh.connect.assert_called_once()
        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["username"] == "testuser"
        assert call_kwargs["pkey"] == mock_key_instance

    @mock.patch("paramiko.Ed25519Key")
    @mock.patch("paramiko.RSAKey")
    @mock.patch("paramiko.SSHClient")
    def test_connect_with_key_content_falls_back_to_ed25519(
        self,
        mock_ssh_class,
        mock_rsa_key,
        mock_ed25519_key,
    ):
        """Test key-content auth falls back to ED25519 when RSA parsing fails."""
        import paramiko

        key_content = "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"
        mock_rsa_key.from_private_key.side_effect = paramiko.SSHException("not rsa")
        mock_key_instance = mock.MagicMock()
        mock_ed25519_key.from_private_key.return_value = mock_key_instance

        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            key_content=key_content,
        )

        result = client._connect()

        assert result == mock_sftp
        call_kwargs = mock_ssh.connect.call_args[1]
        assert call_kwargs["pkey"] == mock_key_instance

    @mock.patch("paramiko.ECDSAKey")
    @mock.patch("paramiko.Ed25519Key")
    @mock.patch("paramiko.RSAKey")
    @mock.patch("paramiko.SSHClient")
    def test_connect_with_invalid_key_content_raises_sftp_error(
        self,
        mock_ssh_class,
        mock_rsa_key,
        mock_ed25519_key,
        mock_ecdsa_key,
    ):
        """Test key-content auth fails with SFTPError when key cannot be parsed."""
        import paramiko

        mock_rsa_key.from_private_key.side_effect = paramiko.SSHException("bad key")
        mock_ed25519_key.from_private_key.side_effect = paramiko.SSHException("bad key")
        mock_ecdsa_key.from_private_key.side_effect = ValueError("bad key")
        mock_ssh_class.return_value = mock.MagicMock()

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            key_content="invalid-key-content",
        )

        with pytest.raises(
            SFTPError,
            match="Could not load private key - unsupported format or invalid key",
        ):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_authentication_exception(self, mock_ssh_class):
        """Test _connect raises SFTPError on authentication failure."""
        import paramiko

        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = paramiko.AuthenticationException("bad creds")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            password="wrong",
        )

        with pytest.raises(SFTPError, match="Check credentials in Secrets Manager"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_authentication_error_does_not_failover(self, mock_ssh_class):
        """Test _connect does not try additional hosts after auth failure."""
        import paramiko

        mock_ssh_fails = mock.MagicMock()
        mock_ssh_fails.connect.side_effect = paramiko.AuthenticationException("bad creds")

        mock_ssh_works = mock.MagicMock()
        mock_ssh_works.open_sftp.return_value = mock.MagicMock()

        # If failover happened, the second client would be used.
        mock_ssh_class.side_effect = [mock_ssh_fails, mock_ssh_works]

        client = SFTPClient(
            hosts=["10.0.1.50", "10.0.2.50"],
            username="testuser",
            password="wrong",
        )

        with pytest.raises(SFTPError, match="Check credentials in Secrets Manager"):
            client._connect()

        assert mock_ssh_class.call_count == 1

    @mock.patch("paramiko.SSHClient")
    def test_connect_ssh_exception(self, mock_ssh_class):
        """Test _connect raises SFTPError on SSH connection error."""
        import paramiko

        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = paramiko.SSHException("connection timeout")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            password="secret",
        )

        with pytest.raises(SFTPError, match="SSH connection failed"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_network_error(self, mock_ssh_class):
        """Test _connect raises SFTPError on network error."""
        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = OSError("Connection refused")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Network error"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_generic_exception(self, mock_ssh_class):
        """Test _connect raises SFTPError on generic error."""
        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = RuntimeError("unknown error")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            hosts=["server.example.com"],
            username="testuser",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Failed to connect"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_failover_to_second_endpoint(self, mock_ssh_class):
        """Test _connect fails over to second endpoint when first fails."""
        mock_ssh_fails = mock.MagicMock()
        mock_ssh_fails.connect.side_effect = OSError("Connection refused")
        
        mock_ssh_works = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh_works.open_sftp.return_value = mock_sftp
        
        # First call returns failing SSH, second returns working SSH
        mock_ssh_class.side_effect = [mock_ssh_fails, mock_ssh_works]

        client = SFTPClient(
            hosts=["10.0.1.50", "10.0.2.50"],
            username="testuser",
            password="secret",
        )

        result = client._connect()

        assert result == mock_sftp
        assert client._connected_host == "10.0.2.50"
        mock_ssh_fails.connect.assert_called_once_with(
            "10.0.1.50",
            port=22,
            username="testuser",
            password="secret",
            timeout=30,
        )
        mock_ssh_works.connect.assert_called_once_with(
            "10.0.2.50",
            port=22,
            username="testuser",
            password="secret",
            timeout=30,
        )
        # Verify both endpoints were attempted
        assert mock_ssh_class.call_count == 2

    @mock.patch("paramiko.SSHClient")
    def test_connect_failover_exhausts_all_endpoints(self, mock_ssh_class):
        """Test _connect fails after all endpoints fail."""
        created_ssh_clients: list[mock.MagicMock] = []

        def build_failing_ssh_client():
            ssh_client = mock.MagicMock()
            ssh_client.connect.side_effect = OSError("Connection refused")
            created_ssh_clients.append(ssh_client)
            return ssh_client

        mock_ssh_class.side_effect = build_failing_ssh_client

        client = SFTPClient(
            hosts=["10.0.1.50", "10.0.2.50", "10.0.3.50"],
            username="testuser",
            password="secret",
        )

        with pytest.raises(SFTPError, match="Failed to connect to any SFTP endpoint"):
            client._connect()
        assert client._connected_host is None
        assert len(created_ssh_clients) == 3

        for expected_host, ssh_client in zip(client._hosts, created_ssh_clients):
            ssh_client.connect.assert_called_once_with(
                expected_host,
                port=22,
                username="testuser",
                password="secret",
                timeout=30,
            )
        
        # Verify all endpoints were attempted
        assert mock_ssh_class.call_count == 3

