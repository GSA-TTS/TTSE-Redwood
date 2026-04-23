"""
Unit tests for custom exception hierarchy.

This module tests:
- Exception hierarchy and inheritance
- Exception instantiation with messages
- Exception types for different error scenarios
- Error message clarity and detail

Tests use pytest for assertions and exception catching.

TODO: Add tests for exception serialization in audit logs
TODO: Add tests for exception wrapping with context
"""

import pytest
from redwood_dataagent.exceptions import (
    RedwoodDataAgentException,
    ConfigurationError,
    ManifestValidationError,
    StorageError,
    SecretsManagerError,
    SFTPError,
    AuditError,
    EncryptionError
)


class TestExceptionHierarchy:
    """Test suite for exception inheritance hierarchy."""
    
    def test_all_custom_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from RedwoodDataAgentException."""
        exception_types = [
            ConfigurationError,
            ManifestValidationError,
            StorageError,
            SecretsManagerError,
            SFTPError,
            AuditError,
            EncryptionError
        ]
        
        for exc_type in exception_types:
            exception = exc_type("Test message")
            assert isinstance(exception, RedwoodDataAgentException)
    
    def test_base_exception_inherits_from_exception(self):
        """Test that base exception inherits from Python's Exception."""
        exception = RedwoodDataAgentException("Test message")
        assert isinstance(exception, Exception)


class TestConfigurationError:
    """Test suite for ConfigurationError exception."""
    
    def test_configuration_error_creation(self):
        """Test creating a ConfigurationError."""
        error = ConfigurationError("Invalid configuration parameter")
        assert str(error) == "Invalid configuration parameter"
    
    def test_configuration_error_can_be_raised(self):
        """Test raising and catching ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            raise ConfigurationError("Missing environment variable")
        
        assert "Missing environment variable" in str(exc_info.value)
    
    def test_configuration_error_inherits_base_exception(self):
        """Test that ConfigurationError inherits from RedwoodDataAgentException."""
        error = ConfigurationError("Test")
        assert isinstance(error, RedwoodDataAgentException)


class TestManifestValidationError:
    """Test suite for ManifestValidationError exception."""
    
    def test_manifest_validation_error_creation(self):
        """Test creating a ManifestValidationError."""
        error = ManifestValidationError("Checksum mismatch")
        assert str(error) == "Checksum mismatch"
    
    def test_manifest_validation_error_with_details(self):
        """Test creating a detailed ManifestValidationError."""
        details = "File file.txt has checksum mismatch: expected abc, got def"
        error = ManifestValidationError(details)
        assert "checksum mismatch" in str(error).lower()
    
    def test_manifest_validation_error_can_be_raised(self):
        """Test raising and catching ManifestValidationError."""
        with pytest.raises(ManifestValidationError) as exc_info:
            raise ManifestValidationError("File integrity check failed")
        
        assert "integrity" in str(exc_info.value).lower()


class TestStorageError:
    """Test suite for StorageError exception."""
    
    def test_storage_error_creation(self):
        """Test creating a StorageError."""
        error = StorageError("Failed to access S3 bucket")
        assert str(error) == "Failed to access S3 bucket"
    
    def test_storage_error_for_bucket_not_found(self):
        """Test creating StorageError for missing bucket."""
        error = StorageError("S3 bucket 'tts-core-dev-gsa-data-landing' not found")
        assert "bucket" in str(error).lower()
    
    def test_storage_error_can_be_raised(self):
        """Test raising and catching StorageError."""
        with pytest.raises(StorageError) as exc_info:
            raise StorageError("Upload to S3 failed")
        
        assert "upload" in str(exc_info.value).lower()


class TestSecretsManagerError:
    """Test suite for SecretsManagerError exception."""

    def test_secrets_manager_error_creation(self):
        """Test creating a SecretsManagerError."""
        error = SecretsManagerError("Secret not found")
        assert str(error) == "Secret not found"

    def test_secrets_manager_error_can_be_raised(self):
        """Test raising and catching SecretsManagerError."""
        with pytest.raises(SecretsManagerError) as exc_info:
            raise SecretsManagerError("Invalid secret JSON")

        assert "secret" in str(exc_info.value).lower()


class TestSFTPError:
    """Test suite for SFTPError exception."""
    
    def test_sftp_error_creation(self):
        """Test creating an SFTPError."""
        error = SFTPError("SFTP connection timeout")
        assert str(error) == "SFTP connection timeout"
    
    def test_sftp_error_for_authentication(self):
        """Test creating SFTPError for auth failure."""
        error = SFTPError("SSH key authentication failed")
        assert "authentication" in str(error).lower()
    
    def test_sftp_error_for_transfer_failure(self):
        """Test creating SFTPError for transfer failure."""
        error = SFTPError("File transfer failed: Connection reset by peer")
        assert "transfer" in str(error).lower()
    
    def test_sftp_error_can_be_raised(self):
        """Test raising and catching SFTPError."""
        with pytest.raises(SFTPError) as exc_info:
            raise SFTPError("Failed to connect to SFTP server")
        
        assert "connect" in str(exc_info.value).lower()


class TestAuditError:
    """Test suite for AuditError exception."""
    
    def test_audit_error_creation(self):
        """Test creating an AuditError."""
        error = AuditError("Failed to emit audit event")
        assert str(error) == "Failed to emit audit event"
    
    def test_audit_error_for_logging_failure(self):
        """Test creating AuditError for logging failure."""
        error = AuditError("Audit sink is unavailable")
        assert "sink" in str(error).lower()
    
    def test_audit_error_with_event_details(self):
        """Test creating detailed AuditError."""
        error = AuditError("Failed to log event 'pipeline_start': JSON encoder error")
        assert "pipeline_start" in str(error)
    
    def test_audit_error_can_be_raised(self):
        """Test raising and catching AuditError."""
        with pytest.raises(AuditError) as exc_info:
            raise AuditError("Audit logger not initialized")
        
        assert "audit" in str(exc_info.value).lower()


class TestEncryptionError:
    """Test suite for EncryptionError exception."""
    
    def test_encryption_error_creation(self):
        """Test creating an EncryptionError."""
        error = EncryptionError("KMS key not found")
        assert str(error) == "KMS key not found"
    
    def test_encryption_error_for_kms_access(self):
        """Test creating EncryptionError for KMS access."""
        error = EncryptionError("Access denied to KMS key")
        assert "access" in str(error).lower() and "kms" in str(error).lower()
    
    def test_encryption_error_for_crypto_failure(self):
        """Test creating EncryptionError for crypto operation."""
        error = EncryptionError("Encryption operation failed")
        assert "encryption" in str(error).lower()
    
    def test_encryption_error_can_be_raised(self):
        """Test raising and catching EncryptionError."""
        with pytest.raises(EncryptionError) as exc_info:
            raise EncryptionError("Failed to decrypt data")
        
        assert "decrypt" in str(exc_info.value).lower()


class TestExceptionCatching:
    """Test suite for exception catching patterns."""
    
    def test_catch_all_redwood_exceptions(self):
        """Test catching all exceptions with base type."""
        exception_types = [
            ConfigurationError("Config error"),
            ManifestValidationError("Manifest error"),
            StorageError("Storage error"),
            SecretsManagerError("Secrets Manager error"),
            SFTPError("SFTP error"),
            AuditError("Audit error"),
            EncryptionError("Encryption error"),
        ]
        
        for exc in exception_types:
            try:
                raise exc
            except RedwoodDataAgentException as e:
                assert isinstance(e, RedwoodDataAgentException)
    
    def test_catch_specific_exception_types(self):
        """Test catching specific exception types separately."""
        # Configuration Error
        try:
            raise ConfigurationError("Config error")
        except ConfigurationError:
            pass  # Expected
        
        # Storage Error
        try:
            raise StorageError("Storage error")
        except StorageError:
            pass  # Expected
        
        # SFTP Error
        try:
            raise SFTPError("SFTP error")
        except SFTPError:
            pass  # Expected
    
    def test_exception_message_preservation(self):
        """Test that exception messages are preserved through raise/catch."""
        original_message = "Original error message with details"
        
        with pytest.raises(StorageError) as exc_info:
            raise StorageError(original_message)
        
        assert str(exc_info.value) == original_message
