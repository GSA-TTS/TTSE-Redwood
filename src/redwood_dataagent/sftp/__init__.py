"""SFTP client module for remote artifact transfer.

Provides SFTPClient for uploading transfer artifacts (archives, manifests)
to receiver endpoints with retry logic, connection pooling, multi-endpoint
failover, and audit logging.

Also provides factory functions for creating SFTP clients with credentials
from AWS Secrets Manager.
"""

from redwood_dataagent.sftp.client import SFTPClient
from redwood_dataagent.sftp.factory import create_sftp_client_from_secrets_manager

__all__ = ["SFTPClient", "create_sftp_client_from_secrets_manager"]
