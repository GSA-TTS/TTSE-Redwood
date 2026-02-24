# ADR 0001: FDE Architecture Design Options (v0.03)


## Status
Proposed


## Context
This ADR captures the initial architecture design notes and options for the TTSA-ITA Federal Data Exchange (FDE) adapters through Option 4 (v0.03).


### Overview


The TTSA ITA effort is focused on designing and prototyping “Federal Data Exchange (FDE) adapters” that can securely transfer data between agency environments over the public internet. While the initial version (v0.03) will demonstrate two adapters communicating end-to-end, the long-term target is an ecosystem of many adapters (a growing “mesh” of agency-specific deployments) that can participate in the same request/authorize/transfer pattern.


The initial version (v0.03) targets a minimal workflow: a receiver initiates a request; a sender reads the requested data from a defined source, packages it as artifacts + manifest, and transfers the payload across organizations under a zero-trust authorization gate. Data is encrypted in transit using HTTPS (mTLS) for control-plane messages and rsync over SSH for data-plane payload transfer; artifacts are staged and landed in per-agency mounted storage encrypted at rest (platform-managed). Each agency owns its own mounted storage; the central access validation/agreement store does not store payload data. The architecture must be flexible enough to support arbitrary data sources (APIs, databases, on-prem systems), large payloads (GB-scale, including PDFs), and future expansion to policy-as-code governance (e.g., Immuta-backed access validation) and higher security environments (IL5).


### Goals


- Deliver a working prototype of two interchangeable adapters (each can act as sender or receiver).
- Support secure data movement across different networks over the public internet (assume HTTPS/443) with encryption in transit and at rest.
- Provide an internal adapter structure that is extensible to many data sources and can support full refresh and delta-based transfers over time.
- Prefer managed/container-native components where possible to reduce ATO overhead, while keeping the design portable for agencies that are not AWS-based.
- Ensure downstream compatibility with Databricks as the storage/analytics platform for the ITA use case (initially IL2 data) as a follow-on integration.


### Specifications


#### Functional requirements


- Adapter interchangeability: each deployment can operate as a sender or receiver.
- Transfer workflow (v0.03):
 - Sender validates request origin (initially via “ugly hack”; later via access validation service).
 - Sender reads from source, compresses, and stages artifacts + manifest in the sender org mounted storage (encrypted at rest, platform-managed).
 - All agent-to-agent and agent-to-control-plane HTTPS calls perform TLS identity validation using mTLS certificates issued by the GSA Private CA (keystore certificates).
 - Sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs a delivery-time authorization check with the access validation service before approving acceptance.
 - Sender transfers artifacts + manifest via rsync over SSH encrypted in transit only after receiver approval.
 - Sender uses a short-lived SSH user certificate issued by a GSA-operated SSH CA to authenticate to the receiver for data-plane transfer.
 - Receiver stores the artifacts + manifest in the receiver org mounted storage (encrypted at rest, platform-managed) until downstream processing completes.
- Data characteristics:
 - Supports structured and unstructured formats, including PDFs; payload size may be GB-scale.
 - Cadence and “delta vs full refresh” must be supported as a roadmap capability.
- Network constraints:
 - Adapters operate across separate agency network boundaries and must communicate over the public internet (typically HTTPS/TCP 443), subject to firewall allowlisting and other restricted inbound/outbound connectivity requirements.


#### Non-functional requirements


- Security:
 - Encryption in transit using TLS for HTTPS control-plane messages and SSH for data-plane payload transfer.
 - Encryption at rest using platform-managed encryption for sender/receiver mounted storage.
 - Mutual TLS (mTLS) for all agent-to-agent and agent-to-control-plane HTTPS communication, using GSA-owned certificates issued by a GSA Private CA (e.g., AWS ACM Private CA) to validate identity and trust.
 - Keystore certificates are owned/operated by the GSA control-plane (Private CA trust anchor); agency agents use certificates issued from this keystore for identity verification.
 - SSH user certificates are issued by a GSA-operated SSH CA for sender authentication during rsync over SSH transfer.
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
  - Sender extracts data from the source system and packages it as one or more files.
  - Sender writes/stages artifacts + manifest into sender-owned mounted storage (encrypted at rest, platform-managed).
  - Optional optimization: sender agent performs a pre-check with the access validation service before initiating transfer.
  - Sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service.
  - Sender transfers artifacts + manifest via rsync over SSH encrypted in transit after receiver approval to support reliable transfers and retries for GB-scale artifacts.
  - Sender authenticates to the receiver using a short-lived SSH user certificate issued by a GSA-operated SSH CA.
  - Sender writes a manifest alongside the payload (e.g., JSON) containing metadata such as dataset identifier, time range, file list, sizes, checksums, compression/encryption method, and schema/version.
  - Receiver stores the artifacts + manifest in the receiver org mounted storage (encrypted at rest, platform-managed).
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
  - The same agency-local FDE agent packages/compresses and stages artifacts + manifest in sender-owned mounted storage (encrypted at rest, platform-managed).
  - The sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service before approving acceptance.
  - The sender transfers artifacts + manifest via rsync over SSH encrypted in transit only after receiver approval; receiver writes artifacts to receiver-owned mounted storage (encrypted at rest, platform-managed).
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
  - The agency agent runs the extraction logic locally (using agent-native connectors), then packages and stages artifacts + manifest in sender-owned mounted storage (encrypted at rest, platform-managed).
  - The sender initiates a delivery attempt to the receiver agent endpoint over HTTPS; the receiver validates sender identity (mTLS) and performs delivery-time authorization check with the access validation service before approving acceptance.
  - The sender transfers artifacts + manifest via rsync over SSH encrypted in transit only after receiver approval; receiver writes artifacts to receiver-owned mounted storage (encrypted at rest, platform-managed).
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
  - Receiver exposes an endpoint to accept a request and perform an explicit receiver-boundary authorization check before accepting a transfer.
  - Sender fetches/loads the source data, compresses the payload, and produces a payload artifact.
  - Sender transfers the payload to the receiver via rsync over SSH encrypted in transit using a short-lived SSH user certificate; receiver writes to mounted storage encrypted at rest (platform-managed).
  - Deliberately minimal: this option is about proving the crypto + interchangeability loop, not long-running data movement.
- Pros & Cons:
  - Pros: fastest way to validate end-to-end cryptographic workflow and adapter interchangeability.
  - Cons: not production-grade for GB-scale transfers; limited retry/resume/observability; requires later refactor toward standard transfer semantics and discovery.
- Evolution path:
  - Replace direct/synchronous transfer with a robust transport backend (e.g., object-store handoff + manifest, multipart uploads, resumable semantics).
  - Introduce stable, standard request/transfer interfaces and a simple registry/discovery mechanism before scaling beyond a pair of adapters.
- Requirements fit:
  - Functional: directly exercises the v0.03 workflow end-to-end (request, authorize, transfer).
  - Non-functional: limited for production (GB-scale reliability, advanced observability, hardened authorization).
  - Scaling model: acceptable for two-adapter prototype; will require evolution to standard interfaces, registry, and robust transfer semantics.


#### Option 5: Apache NiFi MiNiFi C++ as Agency-Local Agent Runtime + HTTPS mTLS Data-plane Transfer


- Description: Each agency deploys an agency-local FDE agent built on Apache NiFi MiNiFi C++ to implement extraction/packaging/transfer as a configurable processor flow. Data-plane transfer uses HTTPS with mTLS (certs issued by a GSA-operated Private CA) so identity and encryption-in-transit are handled consistently by TLS.
- Control-plane policy: GSA-operated NiFi can validate request/manifest schema and enforce allow/deny decisions returned by the access validation service, while the access validation service remains authoritative for agreement decisions.

| Capability | NiFi in control-plane (OOTB) | Custom code in AV/service |
|---|---|---|
| Request/manifest schema validation | Record and schema validation patterns with clear routing and failure paths | Must implement schema validators, error reporting, and versioning |
| Provenance and audit trails | Flow-level visibility and traceability of validation/enforcement steps | Must design event model, storage, retention, and query UX |
| Routing and orchestration | Conditional routing, fan-out, and policy-driven workflows as flow configuration | Must implement workflow engine logic and deployment pipeline for changes |
| Backpressure and rate controls | Built-in queueing/backpressure and flow tuning knobs | Must build throttling/queueing and protect downstream dependencies |
| Integrations | Many connectors for logs/metrics/sinks and standardized “glue” patterns | Must implement and maintain integrations per target system |

| Capability | MiNiFi C++ agent runtime (OOTB) | Custom-coded agent |
|---|---|---|
| Source connectivity | Processor ecosystem and extension sets reduce bespoke connector code | Must build/maintain connectors per source and auth pattern |
| Pipeline composition | Flow-as-config allows composition of extraction, validation, packaging steps | Must implement pipeline framework or hardcode workflows |
| Backpressure and buffering | Built-in queues/backpressure patterns for variable rates | Must implement buffering, rate limits, and protection for sources |
| Retry and failure routing | Standard failure paths and routing semantics in flows | Must implement retry policies, DLQ/quarantine behavior, and observability |
| Standardization across agencies | Common runtime and flow patterns improve interoperability | Risk of divergent implementations and inconsistent behavior |
| Extensibility model | Add processors/flow updates vs full redeploy of application logic | Extensions require code changes, redeploys, and long-term maintenance |

- How it works (v0.03):
  - Receiver initiates a request to the sender over HTTPS; both sides perform TLS identity validation using mTLS certificates issued by the GSA Private CA.
  - Sender executes a MiNiFi flow to extract from agency-local sources, package artifacts + manifest, and stage to sender mounted storage (encrypted at rest, platform-managed).
  - Sender performs a delivery attempt to the receiver endpoint over HTTPS; receiver performs delivery-time authorization with the access validation service before accepting.
  - Sender transfers artifacts + manifest to the receiver via HTTPS mTLS (encrypted in transit); receiver writes to receiver mounted storage (encrypted at rest, platform-managed).

- Pros & Cons:
  - Pros: simplifies trust model by relying on a single PKI system (X.509 via GSA Private CA) for both control-plane and data-plane; MiNiFi processor ecosystem can reduce custom extraction/packaging code; flow-based runtime makes connector additions more configuration-driven.
  - Cons: requires selecting and standardizing MiNiFi processor sets across agencies; some sources will still require custom processors or sidecars; large payload transfers over HTTPS may require additional engineering for resumable semantics, throttling, and robust retry behavior.

- Requirements fit:
  - Functional: supports agency-local extraction with a standardized request/authorize/transfer contract.
  - Non-functional: strong alignment with zero trust and encryption-in-transit via mTLS; at-rest encryption remains platform-managed; data-plane transfer reliability depends on the chosen HTTPS transfer mechanism.
  - Scaling model: scales by distributing flow configurations and processor extensions, but requires strong versioning and governance of flows across agencies.


## Decision
Adopt this ADR as the initial captured set of architecture options through v0.03 / Option 5 for review.


## Consequences
- Enables review/iteration of the options within the implementation repository.
- Later ADRs can supersede or refine this document as decisions become concrete.


## References:
 - https://docs.mage.ai/design/blocks
 - https://docs.mage.ai/design/blocks/data-loader
 - https://docs.mage.ai/design/data-loading
 - https://docs.mage.ai/design/data-pipeline-management
