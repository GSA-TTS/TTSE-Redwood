"""SFTP client module for remote artifact transfer.

Provides SFTPClient for uploading transfer artifacts (archives, manifests)
to receiver endpoints with retry logic, connection pooling, and audit logging.
"""

from redwood_dataagent.sftp.client import SFTPClient

__all__ = ["SFTPClient"]
