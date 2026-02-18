# ADR 0001: FDE Architecture Design Options (v0.03)

## Status
Proposed

## Context
This ADR captures the initial architecture design notes and options for the TTSA-ITA Federal Data Exchange (FDE) adapters through Option 4 (v0.03).

### Overview

The TTSA ITA effort is focused on designing and prototyping “Federal Data Exchange (FDE) adapters” that can securely transfer data between agency environments over the public internet. While the initial version (v0.03) will demonstrate two adapters communicating end-to-end, the long-term target is an ecosystem of many adapters (a growing “mesh” of agency-specific deployments) that can participate in the same request/authorize/transfer pattern.

The initial version (v0.03) targets a minimal workflow: a receiver initiates a request and shares an ephemeral public key; a sender reads the requested data from a defined source, compresses and encrypts it using the provided key, and transfers the encrypted payload across organizations under a zero-trust authorization gate. Each agency owns its own object store; the central access validation/agreement store does not store payload data. The architecture must be flexible enough to support arbitrary data sources (APIs, databases, on-prem systems), large payloads (GB-scale, including PDFs), and future expansion to policy-as-code governance (e.g., Immuta-backed access validation) and higher security environments (IL5).

### Goals

- Deliver a working prototype of two interchangeable adapters (each can act as sender or receiver).
- Support secure data movement across different networks over the public internet (assume HTTPS/443) with encryption using per-request ephemeral keys.
- Provide an internal adapter structure that is extensible to many data sources and can support full refresh and delta-based transfers over time.
- Prefer managed/container-native components where possible to reduce ATO overhead, while keeping the design portable for agencies that are not AWS-based.
- Ensure downstream compatibility with Databricks as the storage/analytics platform for the ITA use case (initially IL2 data) as a follow-on integration.
 

### Specifications

#### Functional requirements

- Adapter interchangeability: each deployment can operate as a sender or receiver.
- Transfer workflow (v0.03):
  - Receiver generates ephemeral keypair per request and sends request + public key.
  - Sender validates request origin (initially via “ugly hack”; later via access validation service).
  - Sender reads from source, compresses, encrypts with receiver public key, and stages artifacts in the sender org mounted storage.
  - All agent-to-agent and agent-to-control-plane HTTPS calls perform TLS identity validation using mTLS certificates issued by the GSA Private CA (keystore certificates).
  - Sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs a delivery-time authorization check with the access validation service before approving acceptance.
  - Sender transfers encrypted artifacts + manifest via a standardized SSH-based protocol only after receiver approval.
  - Receiver stores the encrypted artifacts + manifest in the receiver org mounted storage (temporary landing) until downstream processing completes.
- Data characteristics:
  - Supports structured and unstructured formats, including PDFs; payload size may be GB-scale.
  - Cadence and “delta vs full refresh” must be supported as a roadmap capability.
- Network constraints:
  - Adapters operate across separate agency network boundaries and must communicate over the public internet (typically HTTPS/TCP 443), subject to firewall allowlisting and other restricted inbound/outbound connectivity requirements.

#### Non-functional requirements

- Security:
  - End-to-end encryption of data in transit using per-request keys (ephemeral in memory for POC).
  - Mutual TLS (mTLS) for all agent-to-agent and agent-to-control-plane HTTPS communication, using GSA-owned certificates issued by a GSA Private CA (e.g., AWS ACM Private CA) to validate identity and trust.
  - Keystore certificates are owned/operated by the GSA control-plane (Private CA trust anchor); agency agents use certificates issued from this keystore for identity verification.
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
  - Shared contract (Per Datasource):
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

#### Option 1: Container-based Adapter Service (Cloud-agnostic)

[Diagrams (Mermaid): ADR 0001 Option 1 flow](./0001-fde-architecture-diagrams.md)

- Compute: container orchestration (ECS/Fargate, EKS, Kubernetes, or equivalent)
  - Container model: both sender and receiver agents are deployed as containerized services (container-first packaging).
- Transfer: encrypted artifact handoff via per-agency mounted storage (multipart when large) + manifest
  - Sender extracts data from the source system, packages it as one or more files, then encrypts the payload using the receiver public key.
  - Sender writes/stages encrypted artifacts + manifest into sender-owned mounted storage.
  - Optional optimization: sender agent performs a pre-check with the access validation service before initiating transfer.
  - Sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service.
  - Sender transfers encrypted artifacts + manifest via SSH (multipart/resumable where supported) after receiver approval to support reliable transfers and retries for GB-scale artifacts.
  - Sender writes a manifest alongside the payload (e.g., JSON) containing metadata such as dataset identifier, time range, file list, sizes, checksums, compression/encryption method, and schema/version.
  - Receiver stores the encrypted artifacts + manifest in the receiver org mounted storage (temporary landing).
- Orchestration: workflow engine (optional) for request lifecycle
  - Models the end-to-end request lifecycle as states (requested -> authorized -> extracting -> uploaded -> completed/failed).
  - Coordinates calls to the relevant components (access validation, sender adapter extract job, manifest/payload publication).
  - Provides centralized retries, timeouts, and error handling for long-running, cross-network transfers.
  - Enables tracking and auditing of transfer status (useful for operators and for governance integration).
- Pros & Cons:
  - Pros: container-first deployability across cloud and on-prem environments; strong support for GB-scale transfers; clear production evolution path.
  - Cons: requires an object storage service and a workflow/scheduling capability; some agency environments may need equivalents (e.g., S3-compatible object storage) or an alternate transport backend to implement the same artifact handoff pattern.
- Requirements fit:
  - Functional: supports sender/receiver interchangeability, key exchange, and batch transfer patterns.
  - Non-functional: best support for GB-scale reliability (object handoff + retry/resume), observability, and operational hardening.
  - Scaling model: aligns with control-plane/data-plane split; supports standardized interfaces and centralized discovery/registry.

#### Option 2: Mage AI Embedded in Agency-Local FDE Adapter (Maximize Connector and Pipeline Capabilities)

- Description: Each agency runs the FDE agent as a single deployable unit; Mage capabilities are embedded within the agent runtime to execute connectors and pipelines close to the data. A central service (Mage or non-Mage control-plane) coordinates scheduling/requests and aggregates run status.
- Mage usage:
  - Mage connectors and pipeline runtime are embedded in the agency-local FDE agent (no separate Mage service/UI is required per agency).
  - This option assumes agencies are willing to run the FDE agent container with Mage-enabled extraction capabilities where the data lives.
 - How it works:
  - A central control-plane schedules or triggers runs and calls an agency-local agent job trigger endpoint.
  - The agency-local FDE agent executes the extraction pipeline using Mage connectors with agency-managed credentials and network access.
  - The same agency-local FDE agent packages/compresses/encrypts and stages artifacts in sender-owned mounted storage.
  - The sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service before approving acceptance.
  - The sender transfers encrypted artifacts + manifest via SSH only after receiver approval; receiver writes artifacts to receiver-owned mounted storage.
 - Control-plane boundary:
  - Authorization (Access Validation/DSA checks) remains authoritative before any extraction; central orchestration only triggers agency-local work after approval.
- Pros & Cons:
  - Pros: strongest use of Mage connectors/pipeline runtime; fastest path to integrate many heterogeneous sources when each agency owns its connector configuration.
  - Cons: operational overhead to deploy/operate Mage in many environments; increased ATO surface area per agency; requires consistent packaging/transfer semantics so pipelines do not drift.
- Requirements fit:
  - Functional: strong coverage for source connectivity and extraction; still requires the FDE request/authorization/transfer contract to be implemented consistently.
  - Non-functional: can be production-capable when paired with robust transfer backend and standardized observability, but requires multi-tenant ops controls.
  - Scaling model: scales source extraction across many agencies, but increases platform operations burden (registry, versioning, and rollout governance become critical).

#### Option 3: Mage AI as Control-plane Orchestrator + Adapter Security Wrapper

- Description: Mage (central, GSA-operated) provides scheduling/monitoring and triggers extraction jobs; agency-local agents execute extraction and implement the FDE request/authorization/encryption/transfer protocol. Source connectivity stays within each agency boundary (agency-owned credentials and network access).
 - How it works:
  - Mage triggers an agency agent job via a standard interface (e.g., HTTPS job trigger endpoint) and tracks run status.
  - The agency agent runs the extraction logic locally (using agent-native connectors), then packages/encrypts and stages artifacts in sender-owned mounted storage.
  - The sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service before approving acceptance.
  - The sender transfers encrypted artifacts + manifest via SSH only after receiver approval; receiver writes artifacts to receiver-owned mounted storage.
 - Control-plane boundary:
  - Access Validation/DSA checks remain authoritative for authorization; Mage orchestrates execution after requests are authorized, without requiring direct network/credential access to agency data stores.
 - Connector location:
  - Source connectors execute inside the agency-local agent deployment. Mage remains control-plane only; a full Mage runtime/UI does not need to be deployed per agency.
- Pros & Cons:
  - Pros: clearer ATO boundary by keeping Mage as control-plane only; central scheduling/monitoring without requiring direct agency data access; agency deployments stay focused on adapter runtime.
  - Cons: does not leverage Mage connectors/pipeline runtime for extraction; connector development/configuration remains the responsibility of each agency adapter; still requires a standard job trigger interface and run status contract.
- Requirements fit:
  - Functional: supports orchestration-triggered, agency-local extraction and a consistent request/authorization/transfer contract; source connectors remain adapter-native per agency.
  - Non-functional: can meet security/observability requirements, but requires added operational controls and ATO work for central Mage (GSA-operated).
  - Scaling model: standardizes orchestration and monitoring, but does not remove the need for standard interfaces, registry/discovery, and rollout governance across many agency deployments.

#### Option 4: Minimal Microservices POC (Fastest v0.03)

- Description: Two lightweight services that implement key exchange + compress/encrypt + return payload.
- How it works (v0.03):
  - Receiver exposes an endpoint to mint an ephemeral public key per request (or per session) and returns it to the sender.
  - Sender fetches/loads the source data, compresses, encrypts to the receiver's ephemeral public key, and produces an encrypted payload artifact.
  - Sender transfers the encrypted payload to the receiver only after an explicit receiver-boundary authorization check; receiver decrypts using the matching ephemeral private key and validates the end-to-end workflow.
  - Deliberately minimal: this option is about proving the crypto + interchangeability loop, not long-running data movement.
- Pros & Cons:
  - Pros: fastest way to validate end-to-end cryptographic workflow and adapter interchangeability.
  - Cons: not production-grade for GB-scale transfers; limited retry/resume/observability; requires later refactor toward standard transfer semantics and discovery.
- Evolution path:
  - Replace direct/synchronous transfer with a robust transport backend (e.g., object-store handoff + manifest, multipart uploads, resumable semantics).
  - Introduce stable, standard request/transfer interfaces and a simple registry/discovery mechanism before scaling beyond a pair of adapters.
- Requirements fit:
  - Functional: directly exercises the v0.03 workflow end-to-end (request, ephemeral keys, encrypt/decrypt).
  - Non-functional: limited for production (GB-scale reliability, advanced observability, hardened authorization).
  - Scaling model: acceptable for two-adapter prototype; will require evolution to standard interfaces, registry, and robust transfer semantics.

## Decision
Adopt this ADR as the initial captured set of architecture options through v0.03 / Option 4 for review.

## Consequences
- Enables review/iteration of the options within the implementation repository.
- Later ADRs can supersede or refine this document as decisions become concrete.

## References:
  - https://docs.mage.ai/design/blocks
  - https://docs.mage.ai/design/blocks/data-loader
  - https://docs.mage.ai/design/data-loading
  - https://docs.mage.ai/design/data-pipeline-management
