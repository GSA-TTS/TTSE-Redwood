# TTSE Data Agent MVP Implementation Approach

## 1. MVP (Day-1) Scope & Goals

### Primary Objectives
1. **End-to-End Data Transfer**: Implement a complete flow from Sender Agency (DOT) object storage (S3, Azure Blob, or equivalent) to SFTP to Receiver Agency (GSA)
2. **Parameterized Agencies**: Support dynamic sender and receiver agencies rather than hard-coding DOT and GSA
3. **In-Container Polling (Day 1)**: Sender Agent polls the incoming S3 prefix every 5 minutes for new files; receiver polling follows the same pattern. S3 Events (via SQS/Lambda) are deferred to a future phase to reduce Day 1 resource and permissions complexity.
4. **Security First**: Encryption at rest in S3 and encryption in transit over SSH/SFTP
5. **Operational Visibility**: Structured logging and audit trail

### Phase 1 Deliverables (MVP)
- Sender object storage structure and naming conventions (S3, Blob, or equivalent)
- GSA S3 bucket structure and naming conventions
- Sender Agent flow: review a sender-owned data file, generate the canonical transfer manifest, compress the payload, and stage artifacts for SFTP
- Policy approval step using a dummy always-approve decision for v0.01
- Sender-side SFTP client capability to upload the generated gzip artifact and manifest to the receiver-side SFTP server once packaging is complete
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
│  │ (Sender S3)  │     │ Container        │                 │
│  └──────────────┘     │  - Review File   │                 │
│                       │  - Policy Check  │                 │
│                       │  - Manifest      │                 │
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
│  │ Sender Packaging Output                 │               │
│  │ (gzip + manifest ready for transfer)    │               │
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

1. **Sender Agent Polls Incoming Prefix**: The Sender Agent container scans the configured incoming S3 prefix (e.g. `s3://bucket/incoming/`) on a 5-minute interval. Files with an existing `.done` marker in `processed/` are skipped.
2. **File Picked Up for Processing**: When an unprocessed file is found, the agent picks up the first available file and begins the sender workflow.
3. **Sender Workflow**:
   - Read the intended sender-owned data file from sender-side object storage
   - Generate the canonical transfer manifest from the sender data file metadata
   - Perform policy approval using the MVP default approve path
   - Generate the canonical manifest metadata required for transfer
   - Compress the payload into a gzip archive
   - Stage compressed artifacts in sender-side object storage
4. **SFTP Upload**:
   - Sender connects to GSA's SFTP endpoint as a client
   - Sender triggers SFTP upload as soon as the gzip artifact is generated and ready
   - Sender uploads compressed data and manifest artifacts
   - Receiver-side SFTP landing writes to GSA S3 landing storage
5. **Receiver Workflow**:
   - Receiver Agent polls the GSA landing S3 prefix on a 5-minute interval to detect new transfers
   - Validate checksums against manifest metadata
   - Decompress validated payloads
   - Store validated data in the receiver target bucket

---

## 3. Storage and Endpoint Naming Conventions

Note: For Day 1 planning, these naming conventions are GSA-proposed standards that will be shared with DOT later and refined based on implementation discussions.

### Sender Storage (AWS S3)

**Pattern:** `tts-core-{environment}-{agency}-data-{purpose}`

Examples:

- `tts-core-dev-dot-data-staging`

### GSA Buckets (AWS)

**Pattern:** `tts-core-{environment}-{agency}-data-{purpose}`

| Bucket | Name | Purpose |
|--------|------|---------|
| Receiver Landing | `tts-core-dev-gsa-data-landing` | Inbound landing zone from remote SFTP server |
| Receiver Target | `tts-core-dev-gsa-data-target` | Final destination for validated and extracted data |

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
│       ├── transfer.tar.gz
│       ├── transfer.tar.gz.asc  (future signing)
│       └── manifest.json

tts-core-dev-gsa-data-landing/
├── transfers/
│   └── {transfer_session_id}/
│       ├── transfer.tar.gz
│       └── manifest.json

tts-core-dev-gsa-data-target/
├── transfers/
│   └── {transfer_session_id}/
│       └── {sender_agency}/
│           └── {extracted_files}
```

### AWS Transfer Family SFTP Servers

**Pattern:** `fde-{agency}-{environment}-sftp`

| Server | DNS/Hostname | Purpose |
|--------|--------------|---------|
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
│   ├── exceptions.py
│   ├── audit/
│   ├── receiver/
│   ├── sftp/
│   ├── storage/
│   ├── policy/
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
| Input | `SENDER_DATA_DIRECTORY` | S3 directory path scanned for incoming files (e.g. `s3://bucket/incoming/`); required for sender-mode runs |
| SFTP | `SFTP_HOST` | Receiver-side SFTP endpoint (follow-up PR scope) |
| SFTP | `SFTP_PORT` | SSH and SFTP port (follow-up PR scope) |
| SFTP | `SFTP_USERNAME` | Username used by the sender container (follow-up PR scope) |
| SFTP | `SFTP_PRIVATE_KEY_SECRET_ARN` | Secret location for SSH private key material (follow-up PR scope) |
| Encryption | `S3_ENCRYPTION_TYPE` | At-rest encryption selection (follow-up PR scope) |
| Encryption | `KMS_KEY_ID` | Optional KMS key reference when using SSE-KMS (follow-up PR scope) |
| Policy | `POLICY_APPROVAL_ENDPOINT` | Future integration point for real policy evaluation |

### Runtime Configuration Scope

The full Day 1 target runtime configuration should capture:

- agent mode, tenant, environment, region, and log level
- sender and receiver agency identifiers
- sender data file reference (required for sender-mode Day 1 execution)
- SFTP endpoint, port, username, and secret reference for SSH credentials
- derived staging, landing, and target bucket names
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
- Reviews the sender-owned input file selected for transfer
- Keeps extraction as a future hook and requires a sender-provided data file for Day 1 runs

#### Sender Manifest Generation
- Generates the canonical transfer manifest from sender payload metadata produced by the sender workflow
- Uses the generated manifest as the transfer metadata source for packaging and handoff

#### Policy Approval
- Initial behavior is unconditional approval
- Evolves later to support real policy checks and approval decisions

#### Compression and Manifest Creation
- Compresses payloads using gzip
- Calculates SHA-256 checksums
- Produces the canonical manifest metadata describing file names, sizes, and checksums

#### SFTP Transfer
- Connects from sender to receiver-side SFTP endpoint
- Uses SSH-based transport for encryption in transit
- Starts immediately after the gzip artifact is created and staged for transfer
- Uploads compressed data and manifest artifacts to receiver landing storage

#### Sender Triggering Assumption (Day 1)
- The Sender Agent runs as a scheduled container job that polls the configured `SENDER_DATA_DIRECTORY` S3 prefix every 5 minutes.
- Files already processed are tracked via `.done` marker objects in `processed/`, making runs idempotent.
- S3 Events (S3 Put → SQS → Lambda/container trigger) are the intended future approach but are deferred to reduce Day 1 setup complexity and required permissions.

### 6.3 Receiver Workflow

**Note:** Receiver processes can run on any container platform.
**Day 1 GSA Trigger:** The Receiver Agent polls the GSA landing S3 prefix on a 5-minute interval. S3 Put event-based triggering (SQS/Lambda) is deferred to a future phase.

#### Manifest Validation
- Reads manifest metadata from landing storage
- Recomputes SHA-256 checksums for transferred files
- Confirms transferred payloads match canonical manifest values generated by the sender workflow

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
4. Day 1 sender events are initiated when the polling loop detects an unprocessed file in the incoming S3 prefix.
5. Day 1 receiver events are initiated when the polling loop detects a new transfer in the GSA landing S3 prefix.
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

### Phase 1B: Sender Polling and Sender Workflow
- Implement 5-minute in-container polling loop scanning `SENDER_DATA_DIRECTORY` S3 prefix for unprocessed files
- Implement `.done` marker pattern in `processed/` prefix for idempotent run tracking
- Implement sender-owned file pickup and review at sender side; Day 1 sender runs require a sender-provided data file
- Implement always-approve policy step for MVP
- Implement canonical sender-manifest creation from sender payload metadata
- Implement handoff from sender staging storage to SFTP upload path

### Phase 1C: GSA Landing and Receiver Workflow
- Implement 5-minute in-container polling loop scanning GSA landing S3 prefix for new transfers
- Implement landing-to-validation flow on GSA side
- Implement manifest validation and decompression
- Implement write path from validated payload to GSA target bucket

### Phase 1D: Platform Integrations
- Implement sender storage integration in a way that can support S3, Blob, or equivalent object storage patterns
- Implement GSA AWS-specific integrations for landing, target storage, and polling-based trigger assumptions (S3 event wiring deferred to future phase)
- Implement SFTP endpoint integration and secret retrieval for SSH credentials

### Phase 1E: End-to-End Orchestration and Verification
- Connect sender trigger, sender workflow, SFTP transfer, GSA landing trigger, and receiver workflow into one coherent Day 1 path
- Run end-to-end tests for the happy path and key failure paths such as checksum mismatch or transfer failure
- Validate audit trace continuity using `transfer_session_id`
- Validate container build and runtime assumptions

### Phase 1F: Documentation and Operational Readiness
- Capture sender-side assumptions, including sender-managed trigger setup
- Capture GSA-side assumptions, including polling-based landing detection for Day 1 and S3 event wiring as the future target
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

1. Sender Agent polls the incoming S3 prefix on a 5-minute interval and picks up unprocessed files. Processed files are tracked via `.done` markers.
2. Sender workflow completes sender file review, policy approval, canonical manifest creation, compression, and staging.
3. SFTP transfer uploads compressed data from sender staging to GSA's SFTP endpoint.
4. Receiver Agent polls the GSA landing S3 prefix on a 5-minute interval; on detecting a new transfer, it validates manifest metadata, decompresses the payload, and stores data to the receiver target bucket.
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
