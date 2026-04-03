"""Tests for SFTP client utilities."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from redwood_dataagent.exceptions import StorageError
from redwood_dataagent.sftp.client import SFTPClient


class TestSFTPClientInit:
    """Tests for SFTPClient initialization and configuration."""

    def test_init_with_password(self):
        """Test initialization with password authentication."""
        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret-pass",
            port=2222,
            timeout=60,
        )

        assert client._host == "receiver.example.com"
        assert client._port == 2222
        assert client._username == "sender"
        assert client._password == "secret-pass"
        assert client._timeout == 60

    def test_init_with_key(self, tmp_path):
        """Test initialization with key-based authentication."""
        key_file = tmp_path / "id_rsa"
        key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            key_path=key_file,
        )

        assert client._key_path == key_file
        assert client._password is None

    def test_init_no_auth_method_fails(self):
        """Test initialization fails when no auth method provided."""
        with pytest.raises(StorageError, match="Either password or key_path"):
            SFTPClient(
                host="receiver.example.com",
                username="sender",
            )

    def test_init_key_not_found_fails(self, tmp_path):
        """Test initialization fails when key file not found."""
        with pytest.raises(StorageError, match="SSH key file does not exist"):
            SFTPClient(
                host="receiver.example.com",
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
            host="receiver.example.com",
            username="sender",
            password="secret",
        )
        metadata = client.upload_file(source_file, "/incoming/archive.tar.gz")

        assert metadata["source_path"] == str(source_file)
        assert metadata["remote_path"] == "/incoming/archive.tar.gz"
        assert metadata["file_size_bytes"] == 7
        assert metadata["attempts"] == 1
        mock_sftp.put.assert_called_once()
        mock_sftp.close.assert_called_once()

    def test_upload_file_not_found(self):
        """Test upload fails when local file not found."""
        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="Local file does not exist"):
            client.upload_file(Path("/nonexistent.tar.gz"), "/incoming/")

    def test_upload_dir_fails(self, tmp_path):
        """Test upload fails when source is directory."""
        source_dir = tmp_path / "mydir"
        source_dir.mkdir()

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="Path is not a file"):
            client.upload_file(source_dir, "/incoming/")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_auth_error(self, mock_connect, tmp_path):
        """Test upload fails on authentication error."""
        import paramiko

        mock_connect.side_effect = paramiko.AuthenticationException("bad auth")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="wrong",
        )

        with pytest.raises(StorageError, match="after .* retries"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_ssh_error(self, mock_connect, tmp_path):
        """Test upload fails on SSH error."""
        import paramiko

        mock_connect.side_effect = paramiko.SSHException("connection lost")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="after .* retries"):
            client.upload_file(source_file, "/incoming/archive.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_upload_network_error(self, mock_connect, tmp_path):
        """Test upload fails on network error."""
        mock_connect.side_effect = OSError("Network unreachable")

        source_file = tmp_path / "archive.tar.gz"
        source_file.write_text("content")

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="Failed to read local file"):
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
            host="receiver.example.com",
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
            host="receiver.example.com",
            username="sender",
            password="secret",
            max_retries=2,
            retry_backoff=0.1,
        )

        with pytest.raises(StorageError, match="after .* retries"):
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
            host="receiver.example.com",
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
            host="receiver.example.com",
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
            host="receiver.example.com",
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
            host="receiver.example.com",
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
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="File not found"):
            client.delete_file("/incoming/nonexistent.tar.gz")

    @mock.patch("redwood_dataagent.sftp.client.SFTPClient._connect")
    def test_delete_error(self, mock_connect):
        """Test delete fails on generic error."""
        mock_sftp = mock.MagicMock()
        mock_sftp.remove.side_effect = Exception("permission denied")
        mock_connect.return_value = mock_sftp

        client = SFTPClient(
            host="receiver.example.com",
            username="sender",
            password="secret",
        )

        with pytest.raises(StorageError, match="Failed to delete"):
            client.delete_file("/incoming/file.tar.gz")


class TestSFTPClientConnect:
    """Tests for SFTPClient._connect method with real paramiko interactions."""

    @mock.patch("paramiko.SSHClient")
    def test_connect_with_password_auth(self, mock_ssh_class):
        """Test _connect with password authentication."""
        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp_client.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
            username="testuser",
            password="testpass",
            port=2222,
            timeout=45,
        )

        result = client._connect()

        assert result == mock_sftp
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
    def test_connect_with_key_auth(self, mock_ssh_class, tmp_path):
        """Test _connect with key-based authentication."""
        key_file = tmp_path / "id_rsa"
        key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")

        mock_ssh = mock.MagicMock()
        mock_sftp = mock.MagicMock()
        mock_ssh.open_sftp_client.return_value = mock_sftp
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
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

    @mock.patch("paramiko.SSHClient")
    def test_connect_authentication_exception(self, mock_ssh_class):
        """Test _connect raises StorageError on authentication failure."""
        import paramiko

        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = paramiko.AuthenticationException("bad creds")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
            username="testuser",
            password="wrong",
        )

        with pytest.raises(StorageError, match="authentication failed"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_ssh_exception(self, mock_ssh_class):
        """Test _connect raises StorageError on SSH connection error."""
        import paramiko

        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = paramiko.SSHException("connection timeout")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
            username="testuser",
            password="secret",
        )

        with pytest.raises(StorageError, match="SSH connection failed"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_network_error(self, mock_ssh_class):
        """Test _connect raises StorageError on network error."""
        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = OSError("Connection refused")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
            username="testuser",
            password="secret",
        )

        with pytest.raises(StorageError, match="Network error"):
            client._connect()

    @mock.patch("paramiko.SSHClient")
    def test_connect_generic_exception(self, mock_ssh_class):
        """Test _connect raises StorageError on generic error."""
        mock_ssh = mock.MagicMock()
        mock_ssh.connect.side_effect = RuntimeError("unknown error")
        mock_ssh_class.return_value = mock_ssh

        client = SFTPClient(
            host="server.example.com",
            username="testuser",
            password="secret",
        )

        with pytest.raises(StorageError, match="Failed to connect"):
            client._connect()

