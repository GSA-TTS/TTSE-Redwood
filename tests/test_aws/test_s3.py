"""Tests for AWS S3 client utilities."""

from __future__ import annotations

import builtins
import sys
from unittest import mock

import pytest

from redwood_dataagent.exceptions import StorageError

# Mock boto3 before importing S3Client
sys.modules["boto3"] = mock.MagicMock()

from redwood_dataagent.aws.s3 import S3Client, _get_positive_int_env  # noqa: E402


@pytest.fixture
def mock_boto3_client():
    """Fixture that mocks boto3 for all tests."""
    # The boto3 module is already mocked in sys.modules
    # Get the mock object and reset it for each test
    mock_boto3 = sys.modules["boto3"]
    mock_boto3.reset_mock()

    # Create the mock S3 client with proper exception classes
    mock_s3_client = mock.MagicMock()

    # Create proper exception classes that inherit from Exception
    class NoSuchBucket(Exception):  # noqa: N818
        pass

    class NoSuchKey(Exception):  # noqa: N818
        pass

    # Set up the exceptions attribute
    mock_s3_client.exceptions.NoSuchBucket = NoSuchBucket
    mock_s3_client.exceptions.NoSuchKey = NoSuchKey

    mock_boto3.client.return_value = mock_s3_client
    return mock_boto3


class TestS3Client:
    """Tests for S3Client initialization and configuration."""

    def test_s3client_init_success(self, mock_boto3_client):
        """Test successful S3Client initialization."""
        client = S3Client(aws_region="us-west-2")
        assert client is not None
        assert client._region == "us-west-2"
        mock_boto3_client.client.assert_called_once_with("s3", region_name="us-west-2")

    def test_s3client_init_default_region(self, mock_boto3_client):
        """Test S3Client initializes with default region."""
        client = S3Client()
        assert client._region == "us-east-1"
        mock_boto3_client.client.assert_called_once_with("s3", region_name="us-east-1")

    def test_s3client_init_raises_when_boto3_missing(self):
        """Initialization raises clear ImportError when boto3 cannot be imported."""
        real_import = builtins.__import__

        def _import_fail_boto3(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "boto3":
                raise ImportError("missing boto3")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=_import_fail_boto3):
            with pytest.raises(ImportError, match="boto3 is required"):
                S3Client()


class TestS3TransferTuningEnvParsing:
    """Tests for transfer tuning env helper parsing behavior."""

    def test_get_positive_int_env_returns_default_when_missing(self):
        """Missing env var returns default value."""
        with mock.patch.dict("os.environ", {}, clear=True):
            assert _get_positive_int_env("SOME_MISSING_ENV", 64) == 64

    def test_get_positive_int_env_returns_default_when_invalid(self):
        """Invalid non-integer env var returns default value."""
        with mock.patch.dict("os.environ", {"S3_MULTIPART_THRESHOLD_MB": "not-a-number"}, clear=True):
            assert _get_positive_int_env("S3_MULTIPART_THRESHOLD_MB", 64) == 64

    def test_get_positive_int_env_returns_default_when_non_positive(self):
        """Zero/negative env var returns default value."""
        with mock.patch.dict("os.environ", {"S3_TRANSFER_MAX_CONCURRENCY": "0"}, clear=True):
            assert _get_positive_int_env("S3_TRANSFER_MAX_CONCURRENCY", 8) == 8

    def test_get_positive_int_env_returns_parsed_value_when_valid(self):
        """Valid positive integer env var is parsed and returned."""
        with mock.patch.dict("os.environ", {"S3_TRANSFER_DOWNLOAD_ATTEMPTS": "9"}, clear=True):
            assert _get_positive_int_env("S3_TRANSFER_DOWNLOAD_ATTEMPTS", 5) == 9


class TestS3ClientDownload:
    """Tests for S3Client.download_file method."""

    def test_download_file_success(self, mock_boto3_client, tmp_path):
        """Test successful file download from S3."""
        destination_file = tmp_path / "downloaded.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        # Create the destination file so stat() works
        destination_file.write_text('{"test": "data"}')

        client.download_file("test-bucket", "path/to/file.json", destination_file)
        mock_s3_client.download_file.assert_called_once_with(
            "test-bucket",
            "path/to/file.json",
            str(destination_file),
            Config=mock.ANY,
        )

    def test_download_file_creates_parent_directory(self, mock_boto3_client, tmp_path):
        """Test download creates parent directories if needed."""
        destination_file = tmp_path / "subdir" / "nested" / "file.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        with mock.patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 1024

            client.download_file("test-bucket", "path/to/file.json", destination_file)

            # Parent directories should be created
            assert destination_file.parent.parent.exists()


class TestS3ClientUpload:
    """Tests for S3Client.upload_file method."""

    def test_upload_file_success(self, mock_boto3_client, tmp_path):
        """Test successful file upload to S3."""
        source_file = tmp_path / "test.json"
        source_file.write_text('{"key": "value"}')

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        client.upload_file(source_file, "test-bucket", "path/to/file.json")
        mock_s3_client.upload_file.assert_called_once_with(
            str(source_file),
            "test-bucket",
            "path/to/file.json",
            Config=mock.ANY,
        )

    def test_upload_file_not_exists(self, mock_boto3_client, tmp_path):
        """Test upload fails when local file does not exist."""
        source_file = tmp_path / "nonexistent.json"

        client = S3Client(aws_region="us-east-1")

        with pytest.raises(StorageError, match="Local file does not exist"):
            client.upload_file(source_file, "test-bucket", "path/to/file.json")

    def test_upload_file_is_directory(self, mock_boto3_client, tmp_path):
        """Test upload fails when path is a directory."""
        source_dir = tmp_path / "directory"
        source_dir.mkdir()

        client = S3Client(aws_region="us-east-1")

        with pytest.raises(StorageError, match="Path is not a file"):
            client.upload_file(source_dir, "test-bucket", "path/to/dir")


class TestS3ClientObjectExists:
    """Tests for S3Client.object_exists method."""

    def test_object_exists_true(self, mock_boto3_client):
        """Test object_exists returns True when object exists."""
        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.head_object.return_value = {"ContentLength": 1024}

        exists = client.object_exists("test-bucket", "path/to/file.json")
        assert exists is True

    def test_object_exists_false_nosuchkey(self, mock_boto3_client):
        """Test object_exists returns False when object does not exist."""
        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        mock_s3_client.head_object.side_effect = mock_s3_client.exceptions.NoSuchKey()

        exists = client.object_exists("test-bucket", "nonexistent/key.json")
        assert exists is False


class TestS3ClientDownloadExceptions:
    """Tests for exception handling in S3Client.download_file."""

    def test_download_file_nosuchbucket(self, mock_boto3_client, tmp_path):
        """Test download_file raises StorageError when bucket does not exist."""
        destination_file = tmp_path / "file.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        # Configure the mock to raise NoSuchBucket
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})  # noqa: N806
        mock_s3_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_s3_client.download_file.side_effect = NoSuchBucket("Bucket does not exist")

        with pytest.raises(StorageError, match="S3 bucket does not exist: test-bucket"):
            client.download_file("test-bucket", "path/to/file.json", destination_file)

    def test_download_file_nosuchkey(self, mock_boto3_client, tmp_path):
        """Test download_file raises StorageError when key does not exist."""
        destination_file = tmp_path / "file.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        # Configure the mock to raise NoSuchKey
        NoSuchKey = type("NoSuchKey", (Exception,), {})  # noqa: N806
        mock_s3_client.exceptions.NoSuchKey = NoSuchKey
        mock_s3_client.download_file.side_effect = NoSuchKey("Key does not exist")

        with pytest.raises(StorageError, match="S3 object does not exist"):
            client.download_file("test-bucket", "path/to/file.json", destination_file)

    def test_download_file_oserror(self, mock_boto3_client, tmp_path):
        """Test download_file raises StorageError on OSError (disk access issues)."""
        destination_file = tmp_path / "file.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.download_file.side_effect = OSError("Disk full")

        with pytest.raises(StorageError, match="Failed to write file to"):
            client.download_file("test-bucket", "path/to/file.json", destination_file)

    def test_download_file_generic_exception(self, mock_boto3_client, tmp_path):
        """Test download_file raises StorageError on generic exceptions."""
        destination_file = tmp_path / "file.json"

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.download_file.side_effect = RuntimeError("Unknown error")

        with pytest.raises(StorageError, match="Failed to download S3 object"):
            client.download_file("test-bucket", "path/to/file.json", destination_file)


class TestS3ClientUploadExceptions:
    """Tests for exception handling in S3Client.upload_file."""

    def test_upload_file_nosuchbucket(self, mock_boto3_client, tmp_path):
        """Test upload_file raises StorageError when bucket does not exist."""
        source_file = tmp_path / "file.json"
        source_file.write_text('{"test": "data"}')

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        # Configure the mock to raise NoSuchBucket
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})  # noqa: N806
        mock_s3_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_s3_client.upload_file.side_effect = NoSuchBucket("Bucket does not exist")

        with pytest.raises(StorageError, match="S3 bucket does not exist: test-bucket"):
            client.upload_file(source_file, "test-bucket", "path/to/file.json")

    def test_upload_file_oserror(self, mock_boto3_client, tmp_path):
        """Test upload_file raises StorageError on OSError (file access issues)."""
        source_file = tmp_path / "file.json"
        source_file.write_text('{"test": "data"}')

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.upload_file.side_effect = OSError("File not readable")

        with pytest.raises(StorageError, match="Failed to read file"):
            client.upload_file(source_file, "test-bucket", "path/to/file.json")

    def test_upload_file_generic_exception(self, mock_boto3_client, tmp_path):
        """Test upload_file raises StorageError on generic exceptions."""
        source_file = tmp_path / "file.json"
        source_file.write_text('{"test": "data"}')

        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.upload_file.side_effect = RuntimeError("Unknown error")

        with pytest.raises(StorageError, match="Failed to upload file to s3"):
            client.upload_file(source_file, "test-bucket", "path/to/file.json")


class TestS3ClientObjectExistsExceptions:
    """Tests for exception handling in S3Client.object_exists."""

    def test_object_exists_nosuchbucket(self, mock_boto3_client):
        """Test object_exists returns False on NoSuchBucket exception."""
        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value

        # Configure the mock to raise NoSuchBucket
        NoSuchBucket = type("NoSuchBucket", (Exception,), {})  # noqa: N806
        mock_s3_client.exceptions.NoSuchBucket = NoSuchBucket
        mock_s3_client.head_object.side_effect = NoSuchBucket("Bucket does not exist")

        exists = client.object_exists("test-bucket", "path/to/file.json")
        assert exists is False

    def test_object_exists_generic_exception(self, mock_boto3_client):
        """Test object_exists returns False on generic exceptions."""
        client = S3Client(aws_region="us-east-1")
        mock_s3_client = mock_boto3_client.client.return_value
        mock_s3_client.head_object.side_effect = RuntimeError("Unknown error")

        exists = client.object_exists("test-bucket", "path/to/file.json")
        assert exists is False
