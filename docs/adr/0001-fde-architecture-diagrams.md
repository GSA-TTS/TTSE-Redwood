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
