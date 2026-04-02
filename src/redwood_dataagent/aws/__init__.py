"""AWS service integrations for the Redwood Data Agent.

This package provides AWS service wrappers for:
- S3: Object storage operations
- SFTP: Secure file transfer (future)
- Secrets Manager: Key material retrieval
"""

from .s3 import S3Client

__all__ = ["S3Client"]
