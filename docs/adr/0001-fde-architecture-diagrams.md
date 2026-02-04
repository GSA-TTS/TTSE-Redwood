# ADR 0001 Diagrams: FDE Architecture Options

## Option 1 (Case A): FDE Transfer Flow (Receiver-initiated)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  participant R as Receiver Adapter (Requestor)
  participant AV as Access Validation / Agreement Store
  participant S as Sender Adapter
  participant S3 as S3 (Encrypted Artifact Handoff)
  participant D as Databricks Landing (or downstream)

  R->>R: Generate ephemeral keypair (keep private key)
  R->>S: Data request + identity proof + receiver public key
  S->>AV: Validate request identity + agreement/policy for dataset
  AV-->>S: Authorized (or Denied)

  alt Authorized
    S->>S: Extract data from source system
    S->>S: Compress (gzip) + Encrypt to receiver public key
    S->>S3: Upload encrypted artifact(s) (multipart if large)
    S->>S3: Write manifest (metadata + checksums + file list)
    R->>S3: Download manifest + encrypted artifact(s)
    R->>R: Verify checksums/integrity
    R->>R: Decrypt with ephemeral private key
    R->>D: Land decrypted data
  else Denied
    S-->>R: Denied / error response
  end
```

### Component diagram

```mermaid
flowchart LR
  subgraph ControlPlane[Control-plane]
    AV[Access Validation / Agreement Store]
  end

  subgraph DataPlane[Data-plane]
    R[Receiver Adapter]
    S[Sender Adapter]
    SRC[(Agency Data Source)]
    S3[(S3 Encrypted Handoff + Manifest)]
    DBX[(Databricks Landing)]
  end

  R -->|Request + identity + receiver public key| S
  S -->|AuthZ check| AV
  S -->|Extract| SRC
  S -->|Compress + Encrypt| S3
  R -->|Download + Verify| S3
  R -->|Decrypt + Land| DBX
```

## Option 2: Mage AI as Orchestrator + Agency-Local Adapter Execution

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  participant R as Receiver Adapter (Requestor)
  participant AV as Access Validation / Agreement Store
  participant M as Mage (Central Scheduler/Monitor)
  participant A as Agency-Local Adapter (Extraction + FDE Wrapper)
  participant S3 as Transfer Backend (e.g., S3 Handoff)
  participant D as Databricks Landing (or downstream)

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized (or Denied)

  alt Authorized
    R->>M: Submit authorized job request + receiver public key
    M->>A: Trigger extraction job (HTTPS) + receiver public key
    A->>A: Extract data from agency source system
    A->>A: Compress (gzip) + Encrypt to receiver public key
    A->>S3: Upload encrypted artifact(s) + manifest
    M->>M: Track status/metadata (scheduling/monitoring)
    R->>S3: Download manifest + encrypted artifact(s)
    R->>R: Verify checksums/integrity
    R->>R: Decrypt with ephemeral private key
    R->>D: Land decrypted data
  else Denied
    AV-->>R: Denied / error response
  end
```

### Component diagram

```mermaid
flowchart LR
  subgraph ControlPlane[Control-plane]
    AV[Access Validation / Agreement Store]
    M["Mage: Central Scheduler and Monitor"]
  end
 
  subgraph AgencyBoundary[Agency boundary]
    A["Agency-Local Adapter: Connectors and FDE Wrapper"]
    SRC[(Agency Data Source)]
  end
 
  subgraph ReceiverSide[Receiver side]
    R[Receiver Adapter]
    DBX[(Databricks Landing)]
  end
 
  T["Transfer Backend: S3 Handoff and Manifest"]
 
  R --> AV
  AV --> M
  M --> A
  A --> SRC
  A --> T
  R --> T
  R --> DBX
```

## Option 3: Mage AI Deployed Per-Agency (Maximize Connector and Pipeline Capabilities)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  participant R as Receiver Adapter (Requestor)
  participant AV as Access Validation / Agreement Store
  participant CP as Central Control-plane Scheduler
  participant Mg as Agency-Local Mage Runtime
  participant A as Agency-Local Adapter Wrapper
  participant T as Transfer Backend (e.g., S3 Handoff)
  participant D as Databricks Landing (or downstream)

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized (or Denied)

  alt Authorized
    R->>CP: Submit authorized request + receiver public key
    CP->>Mg: Trigger agency-local pipeline run (HTTPS)
    Mg->>Mg: Execute connectors/pipeline to extract data
    Mg->>A: Hand off extracted data/artifacts for packaging
    A->>A: Compress (gzip) + Encrypt to receiver public key
    A->>T: Upload encrypted artifact(s) + manifest
    CP->>CP: Track run status/metadata
    R->>T: Download manifest + encrypted artifact(s)
    R->>R: Verify checksums/integrity
    R->>R: Decrypt with ephemeral private key
    R->>D: Land decrypted data
  else Denied
    AV-->>R: Denied / error response
  end
```

### Component diagram

```mermaid
flowchart LR
  subgraph ControlPlane[Control-plane]
    AV3[Access Validation / Agreement Store]
    CP3["Central Scheduler and Monitoring"]
  end

  subgraph AgencyBoundary[Agency boundary]
    Mg3["Mage Runtime (Agency-local)"]
    A3["Adapter Wrapper (FDE packaging and transfer)"]
    SRC3[(Agency Data Source)]
  end

  subgraph ReceiverSide[Receiver side]
    R3[Receiver Adapter]
    DBX3[(Databricks Landing)]
  end

  T3["Transfer Backend: S3 Handoff and Manifest"]

  R3 --> AV3
  AV3 --> CP3
  CP3 --> Mg3
  Mg3 --> SRC3
  Mg3 --> A3
  A3 --> T3
  R3 --> T3
  R3 --> DBX3
```
