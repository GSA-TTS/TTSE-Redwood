# ADR 0001: FDE Architecture Design Options (v0.01)

## Status
Proposed

## Context
This ADR captures the initial architecture design notes and options for the TTSA-ITA Federal Data Exchange (FDE) adapters through Option 4 (v0.01).

### Overview

The TTSA ITA effort is focused on designing and prototyping “Federal Data Exchange (FDE) adapters” that can securely transfer data between agency environments over the public internet. While the initial version (v0.01) will demonstrate two adapters communicating end-to-end, the long-term target is an ecosystem of many adapters (a growing “mesh” of agency-specific deployments) that can participate in the same request/authorize/transfer pattern.

The initial version (v0.01) targets a minimal workflow: a receiver initiates a request and shares an ephemeral public key; a sender reads the requested data from a defined source, compresses and encrypts it using the provided key, and returns the encrypted payload for the receiver to decrypt. The architecture must be flexible enough to support arbitrary data sources (APIs, databases, on-prem systems), large payloads (GB-scale, including PDFs), and future expansion to policy-as-code governance (e.g., Immuta-backed access validation) and higher security environments (IL5).

### Goals

- Deliver a working prototype of two interchangeable adapters (each can act as sender or receiver) prior to March.
- Support secure data movement across different networks over the public internet (assume HTTPS/443) with encryption using per-request ephemeral keys.
- Provide an internal adapter structure that is extensible to many data sources and can support full refresh and delta-based transfers over time.
- Prefer AWS-native components where possible to reduce ATO overhead, while keeping the design portable for agencies that are not AWS-based.
- Ensure downstream compatibility with Databricks as the storage/analytics platform for the ITA use case (initially IL2 data).

### Specifications

#### Functional requirements

- Adapter interchangeability: each deployment can operate as a sender or receiver.
- Transfer workflow (v0.01):
  - Receiver generates ephemeral keypair per request and sends request + public key.
  - Sender validates request origin (initially via “ugly hack”; later via access validation service).
  - Sender reads from source, compresses, encrypts with receiver public key, transmits payload.
  - Receiver decrypts with private key and stores/forwards data (e.g., to Databricks landing).
- Data characteristics:
  - Supports structured and unstructured formats, including PDFs; payload size may be GB-scale.
  - Cadence and “delta vs full refresh” must be supported as a roadmap capability.
- Network constraints:
  - Adapters operate across separate agency network boundaries and must communicate over the public internet (typically HTTPS/TCP 443), subject to firewall allowlisting and other restricted inbound/outbound connectivity requirements.

#### Non-functional requirements

- Security:
  - End-to-end encryption of data in transit using per-request keys (ephemeral in memory for POC).
  - Auditability hooks for later governance integration (policy-as-code, identity validation).
- Reliability:
  - Support reliable transfer of GB-scale payloads, including retry/resume mechanisms where appropriate (production target state).
  - Clear error handling and retries for transient failures.
- Extensibility:
  - Pluggable connector pattern to add new data sources without rewriting the adapter core.
- Deployability:
  - Container-first packaging to run in AWS or on-prem/Kubernetes with minimal changes.

### Scaling model (from 2 adapters to many)

#### Control-plane vs data-plane separation

- Control-plane: validates who is requesting, what they are allowed to request, and where to route the request (identity + agreement/policy enforcement).
- Data-plane: performs the actual extraction, compression, encryption, and transfer of large payloads between agency boundaries.

#### Many-adapter reality

- Each agency (and sometimes multiple systems within an agency) may run one or more adapter instances.
- The system must support a growing number of adapters by using standard interfaces, rather than building a separate integration for each adapter pair.
- A scalable approach is to use a shared contract (FDE request + authorization + transfer protocol) and a pluggable connector mechanism for source-specific extraction.
  - Shared contract:
    - Standard request schema (dataset identifier, time range, parameters, response packaging expectations).
    - Standard authorization artifact (POC: static/manual trust; later: policy-based access validation).
    - Standard transfer semantics (encryption/compression, manifest/checksums, status/error reporting).
  - Pluggable connectors:
    - Source-specific extraction modules (API, database, file/object store, etc.) that plug into a consistent adapter core.
    - Enables adding new sources without changing the request/authorization/transfer protocol.

### Operational implications

- A registry/discovery mechanism is needed (even if manual in the POC) to identify which agency adapter serves which datasets, where that adapter can be reached (endpoint), and what sources/connectors it supports.
- Payload transfer should be resilient for GB-scale data (object handoff + manifest is preferred for the target state).
- Observability (logs/metrics/audit events) should be consistent across all adapter deployments to enable governance and troubleshooting at scale.

### Architecture options (summary)

#### Option 1: AWS-Native Adapter Service (Recommended target state)

[Diagrams (Mermaid): ADR 0001 Option 1 flow](./0001-fde-architecture-diagrams.md)

- Compute: ECS/Fargate (or EKS)
- Transfer: encrypted artifact handoff via S3 (multipart uploads) + manifest
  - Sender extracts data from the source system, packages it as one or more files, then encrypts the payload using the receiver public key.
  - Sender uploads the encrypted payload to S3 (multipart upload when large) to support reliable transfers and retries for GB-scale artifacts.
  - Sender writes a manifest alongside the payload (e.g., JSON) containing metadata such as dataset identifier, time range, file list, sizes, checksums, compression/encryption method, and schema/version.
  - Receiver downloads payload + manifest, verifies checksums/integrity, decrypts using its private key, and then lands the decrypted data to the downstream store.
- Orchestration: Step Functions (optional) for request lifecycle
  - Models the end-to-end request lifecycle as states (requested -> authorized -> extracting -> uploaded -> completed/failed).
  - Coordinates calls to the relevant components (access validation, sender adapter extract job, manifest/payload publication).
  - Provides centralized retries, timeouts, and error handling for long-running, cross-network transfers.
  - Enables tracking and auditing of transfer status (useful for operators and for governance integration).
- Pros & Cons:
  - Pros: ATO-friendly AWS-native primitives; strong support for GB-scale transfers; clear production evolution path.
  - Cons: assumes AWS services for the transfer backend (S3/Step Functions); non-AWS agency environments would need an equivalent object storage service (e.g., S3-compatible MinIO/Ceph, Azure Blob Storage, Google Cloud Storage) or an alternate transport backend (e.g., SFTP or HTTPS streaming) to implement the same artifact handoff pattern.
- Requirements fit:
  - Functional: supports sender/receiver interchangeability, key exchange, and batch transfer patterns.
  - Non-functional: best support for GB-scale reliability (object handoff + retry/resume), observability, and operational hardening.
  - Scaling model: aligns with control-plane/data-plane split; supports standardized interfaces and centralized discovery/registry.

#### Option 2: Mage AI as Connector Runtime + Adapter Security Wrapper

- Description: Mage (central, GSA-operated) orchestrates extraction jobs; agency-local adapters execute source extraction and implement the FDE request/authorization/encryption/transfer protocol.
- Note: Safer approach: Run Mage centrally for scheduling/monitoring, but perform data extraction inside each agency via its local adapter (so GSA does not need direct network/credential access to agency data stores).
- How it works:
  - Mage triggers an agency adapter job via a standard interface (e.g., HTTPS job trigger endpoint) and tracks run status.
  - The agency adapter runs the extraction connector locally, then packages/encrypts/transfers the payload using the FDE protocol.
- Control-plane boundary:
  - Access Validation/DSA checks remain authoritative for authorization; Mage orchestrates execution after requests are authorized.
- Connector location:
  - Source connectors run inside the agency adapter deployment; running Mage inside agencies is optional and not required for the central-orchestrator model.
- References:
  - https://docs.mage.ai/design/blocks
  - https://docs.mage.ai/design/blocks/data-loader
  - https://docs.mage.ai/design/data-loading
  - https://docs.mage.ai/design/data-pipeline-management
- Pros & Cons:
  - Pros: accelerates onboarding of heterogeneous sources via connectors; good for rapid ingestion prototyping.
  - Cons: added operational/ATO surface area; Mage does not replace the need to implement the FDE request/authorization/transfer protocol.
- Requirements fit:
  - Functional: strong coverage for source connectivity via connectors; adapter wrapper must still implement request/authorization/transfer.
  - Non-functional: can meet security/observability requirements, but requires added operational controls and ATO work for Mage.
  - Scaling model: helps scale source extraction within adapters; does not remove the need for standard interfaces and registry/discovery.

#### Option 3: Mage AI Deployed Per-Agency (Maximize Connector and Pipeline Capabilities)

- Description: Each agency runs Mage (or a Mage worker/runtime) inside its own boundary to execute connectors and pipelines close to the data; a central service (Mage or non-Mage control-plane) coordinates scheduling/requests and aggregates run status.
- Mage usage:
  - Mage runs inside each agency boundary and is used for its primary strengths: connectors, pipeline runtime, and per-source extraction orchestration.
  - This option assumes agencies are willing to host and operate Mage (or a compatible worker) where the data lives.
- How it works:
  - A central control-plane schedules or triggers runs and calls an agency-local job trigger endpoint.
  - The agency-local Mage instance executes the extraction pipeline using Mage connectors with agency-managed credentials and network access.
  - The agency-local adapter wrapper (or a standard Mage block) packages/compresses/encrypts and transfers the payload using the FDE protocol.
- Control-plane boundary:
  - Authorization (Access Validation/DSA checks) remains authoritative before any extraction; central orchestration only triggers agency-local work after approval.
- Pros & Cons:
  - Pros: strongest use of Mage connectors/pipeline runtime; fastest path to integrate many heterogeneous sources when each agency owns its connector configuration.
  - Cons: operational overhead to deploy/operate Mage in many environments; increased ATO surface area per agency; requires consistent packaging/transfer semantics so pipelines do not drift.
- Requirements fit:
  - Functional: strong coverage for source connectivity and extraction; still requires the FDE request/authorization/transfer contract to be implemented consistently.
  - Non-functional: can be production-capable when paired with robust transfer backend and standardized observability, but requires multi-tenant ops controls.
  - Scaling model: scales source extraction across many agencies, but increases platform operations burden (registry, versioning, and rollout governance become critical).

#### Option 4: Minimal Microservices POC (Fastest v0.01)

- Description: Two lightweight services that implement key exchange + gzip/encrypt + return payload.
- How it works (v0.01):
  - Receiver exposes an endpoint to mint an ephemeral public key per request (or per session) and returns it to the sender.
  - Sender fetches/loads the source data, compresses (e.g., gzip), encrypts to the receiver’s ephemeral public key, and produces an encrypted payload artifact.
  - Sender transfers the encrypted payload to the receiver (simplest: direct HTTPS upload or synchronous response); receiver decrypts using the matching ephemeral private key and validates the end-to-end workflow.
  - Deliberately minimal: this option is about proving the crypto + interchangeability loop, not long-running data movement.
- Pros & Cons:
  - Pros: fastest way to validate end-to-end cryptographic workflow and adapter interchangeability.
  - Cons: not production-grade for GB-scale transfers; limited retry/resume/observability; requires later refactor toward standard transfer semantics and discovery.
- Evolution path:
  - Replace direct/synchronous transfer with a robust transport backend (e.g., object-store handoff + manifest, multipart uploads, resumable semantics).
  - Introduce stable, standard request/transfer interfaces and a simple registry/discovery mechanism before scaling beyond a pair of adapters.
- Requirements fit:
  - Functional: directly exercises the v0.01 workflow end-to-end (request, ephemeral keys, encrypt/decrypt).
  - Non-functional: limited for production (GB-scale reliability, advanced observability, hardened authorization).
  - Scaling model: acceptable for two-adapter prototype; will require evolution to standard interfaces, registry, and robust transfer semantics.

## Decision
Adopt this ADR as the initial captured set of architecture options through v0.01 / Option 4 for review.

## Consequences
- Enables review/iteration of the options within the implementation repository.
- Later ADRs can supersede or refine this document as decisions become concrete.
