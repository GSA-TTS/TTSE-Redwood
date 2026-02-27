# ADR 003: MVP Architecture — FDE Agent V1 POC


## Status
Proposed


## Context
This ADR documents the MVP architecture for the FDE Agent V1 Proof-of-Concept. It accompanies the visual diagrams in [003-mvp-architecture-diagram.md](./003-mvp-architecture-diagram.md).


### Overview

The MVP architecture demonstrates a two-agency data exchange using interchangeable FDE agents that can operate as either a sender or a receiver. The design targets a minimal end-to-end workflow: a receiver agency initiates a data request; a sender agency extracts, compresses, and transfers the requested data across organizational boundaries using SFTP (SSH port 22) as the data-plane transport. Each agency hosts its own AWS Transfer Family SFTP server as an inbound endpoint; agents act as SFTP clients when connecting to the remote agency's server.

Data is encrypted in transit via the SSH protocol and encrypted at rest using AWS-managed encryption appropriate to the storage service (S3 SSE-S3/SSE-KMS for S3 buckets; KMS-based encryption for EFS file systems). A centralized audit trail captures events at every stage of the pipeline for governance and troubleshooting.


### Goals

- Demonstrate a working end-to-end data exchange between two interchangeable FDE agents (sender ↔ receiver).
- Validate SFTP-based (SSH port 22) data transfer across agency boundaries using AWS Transfer Family.
- Ensure encryption in transit (SSH) and at rest (S3 SSE-S3/SSE-KMS, EFS KMS) throughout the pipeline.
- Provide a manifest-driven integrity verification mechanism (SHA-256 checksums).
- Emit structured audit events at every pipeline stage to a central logging service.
- Keep the architecture simple enough for a V1 POC while establishing patterns that can evolve toward production.


### Specifications


#### Functional requirements

- **Agent interchangeability:** each FDE agent deployment can operate as a sender or a receiver.
- **Transfer workflow (V1 POC):**
  - Receiver agent loads a data request configuration specifying the requested data elements.
  - Receiver agent acts as an SFTP client, authenticates with its SSH private key, and uploads the data request to the sender agency's SFTP server (AWS Transfer Family).
  - Sender agent receives the data request via its SFTP server's backend storage.
  - Sender agent extracts requested data elements from one or more source databases.
  - Sender agent compresses artifacts (gzip) and builds a manifest (file list, SHA-256 checksums, metadata).
  - Sender agent writes compressed artifacts + manifest to staging storage (S3 or EFS, encrypted at rest).
  - Sender agent acts as an SFTP client, authenticates with its SSH private key, and uploads the compressed artifacts + manifest to the receiver agency's SFTP server (AWS Transfer Family).
  - Receiver SFTP server writes incoming files to the receiver's S3/EFS landing storage (encrypted at rest).
  - Receiver agent validates manifest checksums (SHA-256), decompresses artifacts (gzip), and stores the extracted data in the target S3 bucket.
- **Data characteristics:**
  - Supports structured data from relational databases (e.g., PostgreSQL, MySQL).
  - Payload compressed with gzip; integrity verified via SHA-256 checksums in a JSON manifest.

#### Non-functional requirements

- **Security:**
  - Encryption in transit: SSH protocol (port 22) for all SFTP transfers between agencies.
  - Encryption at rest: AWS-managed encryption — S3 uses SSE-S3 or SSE-KMS (configured via bucket default encryption); EFS uses KMS-based encryption (configured at file-system creation). These are configuration choices, not automatic defaults.
  - Authentication: SSH public/private key pairs. Each agent holds a private key (client side); each SFTP server validates against configured authorized keys (server side).
  - Audit: structured events emitted at every pipeline stage to a central logging server (Splunk / Datadog).
- **Integrity:**
  - Manifest-driven verification: SHA-256 checksums for all transferred artifacts.
- **Observability:**
  - Audit events include: `data_request_initiated`, `data_request_received`, `pipeline_start`, `extract_data`, `compress`, `manifest_created`, `sftp_transfer`, `validate_manifest`, `decompress`, `store_data`, `pipeline_complete`.
  - Each event includes a `transfer_session_id` for end-to-end correlation.


### Architecture components


#### Receiver Agency (Section 1)

| Component | Description |
|---|---|
| **Data Request Config** | Configuration file specifying the requested data elements, filters, and metadata. |
| **FDE Agent (Receiver Mode)** | Orchestrates the receiver pipeline: initiates data requests (as SFTP client → sender's server), validates manifests, decompresses artifacts, and stores data. Holds an SSH private key for client authentication. |
| **AWS Transfer Family SFTP Server** | Inbound SFTP endpoint (SSH port 22) that receives uploaded artifacts from the sender agent. Configured with authorized keys to validate sender identity. Backend storage is S3 or EFS. |
| **S3 / EFS Landing** | Landing storage where incoming SFTP files are written. Encrypted at rest (S3 SSE-S3/SSE-KMS or EFS KMS). |
| **Validated + Decompressed Files** | Intermediate state after manifest validation and gzip decompression. |
| **Target S3 Storage** | Final destination for extracted data. Encrypted at rest (S3 SSE-S3/SSE-KMS). |


#### Sender Agency (Section 2)

| Component | Description |
|---|---|
| **Source Database(s)** | One or more relational databases (e.g., PostgreSQL, MySQL) from which data elements are extracted. |
| **FDE Agent (Sender Mode)** | Orchestrates the sender pipeline: receives data requests, extracts from sources, compresses + builds manifest, and uploads to the receiver's SFTP server. Holds an SSH private key for client authentication. |
| **S3 / EFS Staging** | Staging storage for compressed artifacts + manifest before SFTP upload. Encrypted at rest (S3 SSE-S3/SSE-KMS or EFS KMS). |
| **AWS Transfer Family SFTP Server** | Inbound SFTP endpoint (SSH port 22) that receives data request uploads from the receiver agent. Configured with authorized keys to validate receiver identity. Backend storage is S3 or EFS. |


#### Audit Trail

| Component | Description |
|---|---|
| **Central Logging Server** | Aggregates structured audit events from both agents (Splunk / Datadog). Enables governance, troubleshooting, and compliance reporting. |


### Transfer flow summary

#### Step 1 — Receiver initiates data request

1. Receiver agent loads the data request configuration.
2. Receiver agent (SFTP client) authenticates with its SSH private key to the **sender's** SFTP server.
3. Receiver agent uploads the data request file via SFTP put (encrypted in transit via SSH).
4. Sender's SFTP server delivers the request to the sender agent via backend storage.

#### Step 2 — Sender extracts and stages data

1. Sender agent extracts requested data elements from source database(s).
2. Sender agent compresses artifacts (gzip).
3. Sender agent builds `manifest.json` (file list, SHA-256 checksums, metadata).
4. Sender agent writes compressed artifacts + manifest to staging storage (encrypted at rest).

#### Step 3 — Sender uploads to receiver

1. Sender agent (SFTP client) authenticates with its SSH private key to the **receiver's** SFTP server.
2. Sender agent uploads compressed artifacts + manifest via SFTP put (encrypted in transit via SSH).
3. Receiver's SFTP server writes files to the receiver's S3/EFS landing storage (encrypted at rest).

#### Step 4 — Receiver pipeline

1. Receiver agent reads `manifest.json` from landing storage.
2. Receiver agent validates file checksums (SHA-256) against manifest.
3. Receiver agent decompresses artifacts (gzip).
4. Receiver agent stores extracted data in the target S3 bucket (encrypted at rest).

> **Key design point:** SFTP servers (AWS Transfer Family) are **inbound-only** endpoints. They do not initiate outbound connections or relay data to other servers. Each agent acts as an SFTP **client** when uploading to the remote agency's SFTP server.


### Encryption model

| Layer | Mechanism | Configuration required |
|---|---|---|
| **In transit** | SSH protocol (port 22) via SFTP | AWS Transfer Family server + SSH key pairs |
| **At rest — S3** | SSE-S3 or SSE-KMS | Bucket default encryption setting |
| **At rest — EFS** | KMS-based encryption | File-system encryption configuration at creation |

> Encryption at rest is an explicit configuration choice per storage resource. It is not a single automatic default across all AWS storage services.


### Audit events

| Event | Emitted by | Payload |
|---|---|---|
| `data_request_initiated` | Receiver Agent | `transfer_session_id` |
| `data_request_received` | Sender Agent | `requested_elements` |
| `pipeline_start` | Both Agents | `transfer_session_id` |
| `extract_data` | Sender Agent | `metadata` |
| `compress` | Sender Agent | `original_bytes`, `compressed_bytes` |
| `manifest_created` | Sender Agent | — |
| `sftp_transfer` | Sender Agent | `dest_host`, `bytes_sent` |
| `validate_manifest` | Receiver Agent | `files_checked`, `all_passed` |
| `decompress` | Receiver Agent | `decompressed_bytes` |
| `store_data` | Receiver Agent | `target_bucket`, `objects_stored` |
| `pipeline_complete` | Receiver Agent | `transfer_session_id` |


### Assumptions and constraints

- **V1 POC scope:** two agencies, single transfer pattern (request → extract → transfer → validate → store). No retry/resume, no delta transfers, no policy-as-code governance.
- **AWS Transfer Family:** each agency operates its own SFTP server; cross-agency connectivity requires firewall allowlisting of SSH port 22.
- **SSH key management:** manual key provisioning in V1 (authorized keys configured on each SFTP server; private keys held by each agent). Production evolution would introduce a certificate authority or secrets management service.
- **Storage flexibility:** the architecture supports either S3 or EFS as backend storage for SFTP servers and staging/landing. The choice is per-agency and depends on operational preferences and access patterns.
- **Source databases:** V1 targets relational databases (e.g., PostgreSQL, MySQL). Future source types (APIs, file stores, etc.) would follow a pluggable connector pattern.


## Decision
Adopt this ADR as the documented MVP architecture for the FDE Agent V1 POC, with accompanying diagrams in [003-mvp-architecture-diagram.md](./003-mvp-architecture-diagram.md).


## Consequences

- Establishes the baseline architecture for V1 POC implementation.
- Diagrams and this document serve as the single source of truth for the MVP component layout, transfer flow, encryption model, and audit contract.
- Later ADRs can supersede or extend this document as the architecture evolves toward production (e.g., retry/resume, certificate-based auth, policy-as-code).


## References

- [ADR 003: MVP Architecture Diagrams](./003-mvp-architecture-diagram.md)
- [AWS Transfer Family Documentation](https://docs.aws.amazon.com/transfer/)
- [S3 Default Encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-encryption.html)
- [EFS Encryption at Rest](https://docs.aws.amazon.com/efs/latest/ug/encryption-at-rest.html)
