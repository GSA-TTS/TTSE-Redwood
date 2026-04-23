"""AWS service integrations for the Redwood Data Agent.

This package provides AWS service wrappers for:
- S3: Object storage operations
- Secrets Manager: Key material and credential retrieval
- SFTP: Secure file transfer configuration
"""

from .s3 import S3Client
from .secrets_manager import SecretsManagerClient

__all__ = ["S3Client", "SecretsManagerClient"]
