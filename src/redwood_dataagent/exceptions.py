"""
Custom exception hierarchy for TTSE Redwood Data Agent.

This module defines domain-specific exceptions to provide clear error handling
throughout the data transfer pipeline.

Architecture note: All exceptions inherit from RedwoodDataAgentException to enable
granular error handling at different pipeline stages.

TODO: Add exception serialization for audit trail integration
"""


class RedwoodDataAgentException(Exception):
    """
    Base exception class for all Redwood Data Agent errors.
    
    All domain-specific exceptions should inherit from this class to enable
    unified error handling and logging throughout the pipeline.
    """
    pass


class ConfigurationError(RedwoodDataAgentException):
    """
    Raised when configuration parameters are invalid or missing.
    
    This includes:
    - Missing required environment variables
    - Invalid parameter values (e.g., malformed agency codes)
    - Type mismatches in configuration
    
    TODO: Add configuration validation helper methods
    """
    pass


class ManifestValidationError(RedwoodDataAgentException):
    """
    Raised when manifest creation or validation fails.
    
    This includes:
    - Missing required manifest fields
    - Invalid checksum algorithm
    - Malformed manifest JSON
    - Checksum mismatches during receiver-side validation
    
    TODO: Add detailed field-level validation error context
    """
    pass


class StorageError(RedwoodDataAgentException):
    """
    Raised when S3 or object storage operations fail.
    
    This includes:
    - S3 bucket access errors
    - File upload/download failures
    - Encryption configuration errors
    - Path construction failures
    
    TODO: Add retry logic integration with exponential backoff
    """
    pass


class SFTPError(RedwoodDataAgentException):
    """
    Raised when SFTP connection or transfer operations fail.
    
    This includes:
    - SSH key loading failures
    - Connection timeouts
    - Authentication failures
    - File transfer failures
    
    TODO: Add connection pooling and keepalive configuration
    """
    pass


class AuditError(RedwoodDataAgentException):
    """
    Raised when audit event logging fails.
    
    This includes:
    - Failed event serialization
    - Unable to write to audit sink
    - Missing correlation IDs
    
    TODO: Implement fallback audit sink for critical failures
    """
    pass


class EncryptionError(RedwoodDataAgentException):
    """
    Raised when encryption operations fail.
    
    This includes:
    - KMS key access errors
    - Encryption/decryption failures
    - Invalid encryption configuration
    
    TODO: Add key rotation support
    """
    pass


class PolicyApprovalError(RedwoodDataAgentException):
    """
    Raised when policy approval evaluation fails or is denied.
    
    This includes:
    - Invalid sender/receiver agency codes
    - Policy validation failures
    - Transfer compliance rejections
    - Malformed policy request parameters
    
    TODO: Add detailed policy rejection reasons for audit trail
    """
    pass
