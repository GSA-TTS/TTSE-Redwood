"""
Storage module for TTSE Redwood Data Agent.

This module provides storage naming conventions, path builders, and interfaces
for secure multi-cloud data transfer with clear operational semantics.

Day 1 Storage Capabilities:
- Sender-side storage conventions (staging bucket)
- GSA receiver-side storage conventions (landing and target buckets)
- Path builders for transfer artifacts and decompressed data
- Storage purpose classification (staging, landing, target)
- Agency-prefixed naming for multi-tenant isolation

Example usage:
    from redwood_dataagent.storage import (
        FileModeStoragePath,
        QueryModeStoragePath,
        StoragePurpose,
        ReceiverStoragePath,
        build_sender_bucket,
        build_receiver_bucket,
    )
    
    # Build bucket names for sender (DOT) and receiver (GSA)
    sender_bucket = build_sender_bucket(
        agency="dot",
        environment="dev",
        purpose=StoragePurpose.STAGING,
    )
    # Result: "tts-core-dev-dot-data-staging"
    
    receiver_bucket = build_receiver_bucket(
        agency="gsa",
        environment="dev",
        purpose="landing",
    )
    # Result: "tts-core-dev-gsa-data-landing"
    
    # Build transfer paths with manifest
    transfer_path = FileModeStoragePath.transfers(
        transfer_session_id="transfer-001",
        file_name="data.tar.gz",
    )
    # Result: "file_mode/transfers/transfer-001/data.tar.gz"
    
    manifest_path = FileModeStoragePath.transfers(
        transfer_session_id="transfer-001",
        file_name="manifest.json",
    )
    # Result: "file_mode/transfers/transfer-001/manifest.json"

    query_result_path = QueryModeStoragePath.transfers(
        transfer_session_id="transfer-002",
        file_name="results.csv",
    )
    # Result: "query_mode/transfers/transfer-002/results.csv"
    
    # Build extraction paths on receiver
    extracted_path = ReceiverStoragePath.extracted(
        transfer_session_id="transfer-001",
        file_name="records.csv",
    )
    # Result: "extracted/transfer-001/records.csv"
"""

from redwood_dataagent.storage.conventions import (
    FileModeStoragePath,
    QueryModeStoragePath,
    ReceiverStoragePath,
    StoragePurpose,
    build_receiver_bucket,
    build_sender_bucket,
)

__all__ = [
    "StoragePurpose",
    "FileModeStoragePath",
    "QueryModeStoragePath",
    "ReceiverStoragePath",
    "build_sender_bucket",
    "build_receiver_bucket",
]
