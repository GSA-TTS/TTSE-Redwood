"""Receiver agent module for TTSE Redwood Data Agent.

This package contains receiver-side functionality for:
- Landing zone ingest from SFTP
- Manifest validation and checksum verification
- Archive decompression
- Target persistence with idempotency
"""

from redwood_dataagent.receiver.landing import ReceiverLandingZone

__all__ = ["ReceiverLandingZone"]
