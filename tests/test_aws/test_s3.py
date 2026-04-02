"""Tests for AWS S3 client utilities."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from redwood_dataagent.exceptions import StorageError


# Mock boto3 before importing S3Client
sys.modules["boto3"] = mock.MagicMock()

from redwood_dataagent.aws.s3 import S3Client


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
    class NoSuchBucket(Exception):
        pass
    
    class NoSuchKey(Exception):
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
        mock_s3_client.download_file.assert_called_once_with("test-bucket", "path/to/file.json", str(destination_file))

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
        mock_s3_client.upload_file.assert_called_once_with(str(source_file), "test-bucket", "path/to/file.json")

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
