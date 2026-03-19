# TTSE Data Agent MVP Implementation Approach

## 1. MVP (Day-1) Scope & Goals

### Primary Objectives
1. **End-to-End Data Transfer**: Implement a complete flow from Sender Agency (DOT) object storage (S3, Azure Blob, or equivalent) to SFTP to Receiver Agency (GSA)
2. **Parameterized Agencies**: Support dynamic sender and receiver agencies rather than hard-coding DOT and GSA
3. **Event-Driven Architecture**: Sender-side storage event triggers the Sender Agent container; GSA S3 Put event triggers receiver processing
4. **Security First**: Encryption at rest in S3 and encryption in transit over SSH/SFTP
5. **Operational Visibility**: Structured logging and audit trail

### Phase 1 Deliverables (MVP)
- Sender object storage structure and naming conventions (S3, Blob, or equivalent)
- GSA S3 bucket structure and naming conventions
- Sender Agent flow: data extraction to S3 staging using a dummy module initially
- Policy approval step using a dummy always-approve decision for v0.01
- SFTP transfer capability to the receiver side
- AWS infrastructure documentation at naming and interface level
- Structured audit logging with `transfer_session_id` correlation
- Configuration management for dynamic sender and receiver agencies
- Encryption at rest and in transit
- Unit tests for core components
- Container build configuration using the existing Dockerfile

### Phase 2+ (Future Iterations)
- Real data extraction from sender-side databases
- Policy engine with actual validations
- Receiver-side deployment on a container orchestration platform where applicable
- Retry and resume mechanisms
- Delta transfers
- Certificate-based authentication

---

## 2. Architecture Overview

### Component Layout

```
┌─────────────────────────────────────────────────────────────┐
│ SENDER AGENCY (DOT)                                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐     ┌──────────────────┐                 │
│  │ Source Data  │────▶│ Sender Agent     │                 │
│  │ (Mock)       │     │ Container        │                 │
│  └──────────────┘     │  - Extract       │                 │
│                       │  - Policy Check  │                 │
│                       │  - Compress      │                 │
│                       │  - Audit Log     │                 │
│                       └────────┬─────────┘                 │
│                                │                           │
│  ┌──────────────────────────────▼──────────┐               │
│  │ Sender Object Storage                    │ (Encrypted)   │
│  │ (S3 / Blob / equivalent)                 │               │
│  │ - /transfers/...                        │               │
│  └─────────────────────────────────────────┘               │
│                                │                           │
│  ┌──────────────────────────────▼──────────┐               │
│  │ AWS Transfer Family SFTP Server         │ (SSH Port 22) │
│  │ (Inbound only - future flexibility)     │               │
│  └─────────────────────────────────────────┘               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                           ▲
                           │ SFTP Upload
                           │ (Encrypted in transit)
                           │
┌─────────────────────────────────────────────────────────────┐
│ RECEIVER AGENCY (GSA)                                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────┐                │
│  │ AWS Transfer Family SFTP Server         │ (SSH Port 22) │
│  │ (Inbound - receives data from DOT)      │               │
│  └──────────────────┬──────────────────────┘               │
│                     │                                      │
│  ┌──────────────────▼─────────────────────┐                │
│  │ S3 gsa-data-{env}-landing              │ (Encrypted)    │
│  │ - /transfers/...                       │                │
│  └──────────────────┬─────────────────────┘                │
│                     │                                      │
│  ┌──────────────────▼─────────────────────┐                │
│  │ Receiver Agent Container               │                │
│  │ (platform-specific deployment)         │                │
│  │ - Validate Manifest                    │                │
│  │ - Decompress                           │                │
│  │ - Audit Log                            │                │
│  └──────────────────┬─────────────────────┘                │
│                     │                                      │
│  ┌──────────────────▼─────────────────────┐                │
│  │ S3 gsa-data-{env}-target               │ (Encrypted)    │
│  │ - /extracted/...                       │                │
│  └────────────────────────────────────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ CENTRAL AUDIT TRAIL                                         │
├─────────────────────────────────────────────────────────────┤
│ CloudWatch Logs / Splunk / Datadog                          │
│ - Correlated by transfer_session_id                         │
│ - Events cover sender, transfer, validation, and storage    │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Day 1 MVP Transfer Flow

**Key Difference from ADR 003:** The Day 1 MVP does not use bidirectional requests.

1. **Sender Storage Event Triggered at DOT**: A file arrives in DOT sender-side object storage (for example S3 Put, Blob created, or equivalent event).
2. **Sender Event to Sender Agent**: Sender agency configures its own eventing to trigger the Sender Agent container.
3. **Sender Workflow**:
   - Extract mock data or read uploaded file
   - Perform policy approval using the MVP default approve path
   - Compress the payload and generate manifest metadata
   - Stage compressed artifacts in sender-side object storage
4. **SFTP Upload**:
   - Sender connects to GSA's SFTP endpoint as a client
   - Sender uploads compressed data and manifest artifacts
   - Receiver-side SFTP landing writes to GSA S3 landing storage
5. **Receiver Workflow**:
   - GSA configures S3 Put event on landing bucket to trigger receiver processing
   - Validate checksums against manifest metadata
   - Decompress validated payloads
   - Store validated data in the receiver target bucket

---

## 3. Storage and Endpoint Naming Conventions

Note: For Day 1 planning, these naming conventions are GSA-proposed standards that will be shared with DOT later and refined based on implementation discussions.

### Sender Storage (Cloud-Agnostic)

**Pattern:** `{agency}-data-{environment}-{purpose}`

Examples:

- AWS S3: `dot-data-dev-staging`
- Azure Blob container: `dot-data-dev-staging`
- Equivalent object store in other clouds or on-prem

### GSA Buckets (AWS)

**Pattern:** `{agency}-data-{environment}-{purpose}`

| Bucket | Name | Purpose |
|--------|------|---------|
| Receiver Landing | `gsa-data-dev-landing` | Inbound landing zone from remote SFTP server |
| Receiver Target | `gsa-data-dev-target` | Final destination for validated and extracted data |

**Naming Rules:**
- `{agency}` uses a short code such as dot, gsa, or usda
- `{environment}` uses values such as dev, staging, or prod
- `{purpose}` uses values such as staging, landing, or target
- Use lowercase and hyphens only

### S3 Folder Structure

```
sender-data-staging/
├── transfers/
│   └── {transfer_session_id}/
│       ├── data.tar.gz
│       ├── data.tar.gz.asc  (future signing)
│       └── manifest.json

gsa-data-dev-landing/
├── transfers/
│   └── {transfer_session_id}/
│       ├── data.tar.gz
│       └── manifest.json

gsa-data-dev-target/
├── extracted/
│   └── {transfer_session_id}/
│       └── {extracted_files}
```

### AWS Transfer Family SFTP Servers

**Pattern:** `fde-{agency}-{environment}-sftp`

| Server | DNS/Hostname | Purpose |
|--------|--------------|---------|
| DOT SFTP | `fde-dot-dev-sftp.transfer.amazonaws.com` | Inbound endpoint kept for future flexibility |
| GSA SFTP | `fde-gsa-dev-sftp.transfer.amazonaws.com` | Day 1 inbound endpoint for files transferred from DOT |

**Configuration:**
- SSH port 22 only
- SSH key-based authentication
- Logging enabled
- Backend storage mapped to encrypted landing storage

---

## 4. Implementation Structure

### Directory Layout (Current Plan)

```
ttse-redwood/
├── src/redwood_dataagent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   ├── agent.py
│   ├── logging_utils.py
│   ├── audit/
│   ├── sender/
│   ├── receiver/
│   ├── aws/
│   └── models/
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_agent.py
│   ├── test_audit/
│   ├── test_sender/
│   ├── test_receiver/
│   ├── test_aws/
│   └── test_models/
├── docs/
│   ├── adr/
│   ├── mvp/
│   ├── architecture/
│   ├── operations/
│   └── reference/
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## 5. Configuration Parameters

### Environment Variables (Extended)

| Area | Parameter | Purpose |
|------|-----------|---------|
| Core | `AGENT_MODE` | Indicates sender or receiver execution mode |
| Core | `TENANT` | Agency or tenant identifier |
| Core | `ENVIRONMENT` | Deployment environment such as dev, staging, or prod |
| Core | `AWS_REGION` | AWS region for runtime integrations |
| Core | `LOG_LEVEL` | Logging verbosity |
| Core | `TRANSFER_SESSION_ID` | Correlation identifier for one transfer session |
| Agency | `SENDER_AGENCY` | Sender agency code |
| Agency | `RECEIVER_AGENCY` | Receiver agency code |
| SFTP | `SFTP_HOST` | Receiver-side SFTP endpoint |
| SFTP | `SFTP_PORT` | SSH and SFTP port |
| SFTP | `SFTP_USERNAME` | Username used by the sender container |
| SFTP | `SFTP_PRIVATE_KEY_SECRET_ARN` | Secret location for SSH private key material |
| S3 | `STAGING_BUCKET` | Sender staging bucket |
| S3 | `LANDING_BUCKET` | Receiver landing bucket |
| S3 | `TARGET_BUCKET` | Receiver target bucket |
| Encryption | `S3_ENCRYPTION_TYPE` | At-rest encryption selection |
| Encryption | `KMS_KEY_ID` | Optional KMS key reference when using SSE-KMS |
| Policy | `POLICY_APPROVAL_ENDPOINT` | Future integration point for real policy evaluation |

### Runtime Configuration Scope

The runtime configuration should capture:

- agent mode, tenant, environment, region, and log level
- sender and receiver agency identifiers
- SFTP endpoint, port, username, and secret reference for SSH credentials
- staging, landing, and target bucket names
- encryption mode and optional KMS key reference
- transfer session identifier for audit correlation

---

## 6. Module Details

### 6.1 Audit Module

**Purpose:** Structured event emission for compliance and troubleshooting.

**Day 1 Events:**

- `pipeline_start`
- `extract_data`
- `policy_check`
- `compress`
- `manifest_created`
- `sftp_transfer_start`
- `sftp_transfer_complete`
- `validate_manifest`
- `decompress`
- `store_data`
- `pipeline_complete`

### 6.2 Sender Workflow

#### Extraction
- Generates dummy CSV or JSON payloads for initial testing
- Evolves later to pull from sender-side source systems and databases

#### Policy Approval
- Initial behavior is unconditional approval
- Evolves later to support real policy checks and approval decisions

#### Compression and Manifest Creation
- Compresses payloads using gzip
- Calculates SHA-256 checksums
- Produces manifest metadata describing file names, sizes, and checksums

#### SFTP Transfer
- Connects from sender to receiver-side SFTP endpoint
- Uses SSH-based transport for encryption in transit
- Uploads compressed data and manifest artifacts to receiver landing storage

#### Sender Triggering Assumption (Day 1)
- Sender agency owns and configures its own event trigger from sender storage to sender container runtime.
- Trigger mechanism is implementation-specific to sender platform (for example S3 Put, Blob created, or equivalent event source).

### 6.3 Receiver Workflow

**Note:** Receiver processes can run on any container platform.
**Day 1 GSA Trigger:** GSA configures S3 Put event on landing bucket to trigger validation and decompression flow.

#### Manifest Validation
- Reads manifest metadata from landing storage
- Recomputes SHA-256 checksums for transferred files
- Confirms transferred payloads match sender-provided manifest values

#### Decompression
- Extracts gzip-compressed artifacts after validation succeeds
- Produces uncompressed files ready for target storage

#### Target Storage
- Writes validated and decompressed output to the receiver target bucket
- Preserves encryption-at-rest settings required by the deployment

### 6.4 Data Models

**Day 1 MVP:** Only manifest metadata is required. Bidirectional request payloads are out of scope.

Note: The Day 1 manifest definition below is the initial GSA-proposed contract. It should be treated as the starting point to share with DOT once coordination begins, with refinement expected after implementation discussions.

The Day 1 manifest should be treated as the receiver validation contract and should capture:

Required top-level manifest details:

- manifest version, for example `1.0`
- transfer session identifier
- sender agency identifier
- receiver agency identifier
- manifest creation timestamp
- checksum algorithm used for validation
- total file count

Required file-level details for each transferred file:

- file name
- file size in bytes
- SHA-256 checksum
- file role if needed, for example `data`; this can remain simple for Day 1 and expanded later only if multiple transferred file types are introduced

Recommended operational details for Day 1:

- compression type used for the payload
- source environment identifier
- target environment identifier
- transfer date or business date if relevant to downstream processing

Optional future metadata:

- file path or logical object key within the transfer package, if future workflows need to preserve sender-side object structure or support multi-file packaging

Day 1 validation rule:

- GSA receiver flow should treat the manifest as the source of truth for integrity checks and validate that every expected file is present and that each checksum matches before decompression.

---

## 7. Security & Encryption

### Encryption at Rest
- Sender-side object storage should use approved at-rest encryption for the sender platform.
- GSA S3 buckets should use an approved encryption mode such as SSE-S3 or SSE-KMS.
- Configuration is expected to be enforced at the storage-resource level.

### Encryption in Transit
- All inter-agency file transfer should use SSH/SFTP over port 22
- SSH key-based authentication should be used for the Day 1 MVP

### Key Rotation (Future)
- Operational rotation guidance should live under `docs/operations/`

---

## 8. Audit & Logging

### Audit Event Flow
1. Every operation emits a structured event.
2. Each event includes `transfer_session_id` for correlation.
3. Events are expected to flow through centralized logging and observability tooling.
4. Day 1 sender events are initiated by sender-configured storage event triggers.
5. Day 1 receiver events are initiated by GSA S3 Put event on landing storage.
6. Sender events cover extraction, approval, compression, manifest creation, transfer start, transfer complete, and pipeline completion.
7. Receiver events cover validation, decompression, storage, and pipeline completion.

### Audit Event Content

Each audit record should include, as applicable:

- event name
- transfer session identifier
- sender agency
- receiver agency
- timestamp
- destination host for transfer events
- bytes transferred or processed
- stage outcome details where available

---

## 9. Implementation Phases (High Level Plan)
Note: this sequence is intentionally high level and can be adjusted as implementation progresses.

### Phase 1A: Shared Foundation
- Define GSA's initial Day 1 manifest and transfer contract: payload packaging approach, required manifest fields, transfer session correlation, audit event names, and naming conventions
- Extend configuration for sender and receiver parameters
- Establish logging, audit, and error-handling expectations
- Define storage naming and folder conventions for sender storage and GSA landing and target buckets as GSA's initial proposal for later sender alignment

### Phase 1B: Sender Trigger and Sender Workflow
- Define sender-side trigger assumption and integration point from sender object storage to sender container runtime
- Implement mock extraction or input-file pickup at sender side
- Implement always-approve policy step for MVP
- Implement compression and manifest creation
- Implement handoff from sender staging storage to SFTP upload path

### Phase 1C: GSA Landing and Receiver Workflow
- Define GSA landing bucket event trigger using S3 Put event
- Implement landing-to-validation flow on GSA side
- Implement manifest validation and decompression
- Implement write path from validated payload to GSA target bucket

### Phase 1D: Platform Integrations
- Implement sender storage integration in a way that can support S3, Blob, or equivalent object storage patterns
- Implement GSA AWS-specific integrations for landing, target storage, and event trigger wiring assumptions
- Implement SFTP endpoint integration and secret retrieval for SSH credentials

### Phase 1E: End-to-End Orchestration and Verification
- Connect sender trigger, sender workflow, SFTP transfer, GSA landing trigger, and receiver workflow into one coherent Day 1 path
- Run end-to-end tests for the happy path and key failure paths such as checksum mismatch or transfer failure
- Validate audit trace continuity using `transfer_session_id`
- Validate container build and runtime assumptions

### Phase 1F: Documentation and Operational Readiness
- Capture sender-side assumptions, including sender-managed trigger setup
- Capture GSA-side assumptions, including S3 Put event setup on landing bucket
- Update `docs/operations/`, `docs/architecture/`, `docs/reference/`, and `docs/mvp/`
- Prepare GSA-owned manifest and naming convention proposal to share with DOT when coordination begins
- Document open items that remain outside Day 1 scope, such as production policy checks, retries, and non-happy-path recovery

---

## 10. Dependency Management

### Planned Dependencies

Runtime dependencies:

- `boto3` for AWS SDK integration
- `botocore` for AWS SDK support
- `paramiko` for SSH and SFTP support
- `pydantic` as optional schema validation support

Test dependencies:

- `pytest` for unit and integration testing
- `pytest-cov` for coverage reporting
- `moto` for mocked AWS service behavior
- `pytest-mock` for mocking utilities

---

## 11. Branch Strategy

### Branch Naming Convention

- `feature/fde-{feature}-{description}`
- `fix/fde-{component}-{description}`
- `refactor/fde-{component}-{description}`
- `test/fde-{component}-{testtype}`

### MVP Work Branches (off `feature/core-redwood-dataagent-bootstrap`)

| Branch | Purpose |
|--------|---------|
| `feature/fde-config-extensions` | Extended config for agencies and transfer parameters |
| `feature/fde-audit-module` | Audit event framework |
| `feature/fde-sender-workflow` | Sender extraction, compression, and staging |
| `feature/fde-sftp-transfer` | SFTP client integration |
| `feature/fde-receiver-workflow` | Receiver validation, decompression, and storage |
| `feature/fde-aws-integration` | S3 and secret-store integration |
| `feature/fde-end-to-end-workflow` | Agent orchestration and integration tests |
| `feature/fde-documentation` | MVP and operational documentation |
---

## 14. Success Criteria (Done Definition)

MVP Day 1 is complete when:

1. Sender-side storage event (S3 Put, Blob created, or equivalent) triggers the Sender Agent container, configured by sender agency.
2. Sender workflow completes mock extraction, policy approval, compression, and staging.
3. SFTP transfer uploads compressed data from sender staging to GSA's SFTP endpoint.
4. GSA S3 Put event on landing bucket triggers receiver workflow to validate manifest metadata, decompress payloads, and store data to the receiver target bucket.
5. Day 1 audit events are emitted with the correct `transfer_session_id`.
6. Configuration supports dynamic sender and receiver agencies.
7. S3 encryption at rest is enabled.
8. SFTP encryption in transit is enforced.
9. Unit tests cover core behavior.
10. Container build completes successfully.

---

## Document Versions

| Date | Author | Status |
|------|--------|--------|
| 2026-03-17 | Heman/Siva | Draft to ready for approval |
