# ADR 0001 Diagrams: FDE Architecture Options (v0.03)

## Option 1: Container-based Adapter Service (Cloud-agnostic)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant RMS as Receiver Mounted Storage<br/>(Encrypted Temporary Landing)
    participant R as Receiver Agent (Requestor)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
  end
  box "Sender org"
    participant S as Sender Agent
    participant SMS as Sender Mounted Storage<br/>(Encrypted Temporary Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>S: Data request + identity proof + receiver public key
  S->>AV: Validate request identity + agreement/policy for dataset + receiver acceptance
  AV-->>S: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    S->>S: Extract data from source system
    S->>S: Compress + Encrypt to receiver public key
    S->>SMS: Write encrypted artifact(s) (multipart if large)
    S->>SMS: Write manifest (metadata + checksums + file list)
    S->>AV: Delivery-time authorization check
    AV-->>S: Approved (or Denied)
    S->>R: Transfer encrypted artifacts and manifest via SSH protocol
    R->>RMS: Write encrypted artifacts and manifest to mounted storage
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

  subgraph SenderOrg[Sender org]
    S[Sender Agent]
    SRC[(Agency Data Source)]
    SMS[(Sender Mounted Storage<br/>Encrypted Temporary Staging)]
  end

  subgraph ReceiverOrg[Receiver org]
    RMS[(Receiver Mounted Storage<br/>Encrypted Temporary Landing + Manifest)]
    R[Receiver Agent]
  end

  R -->|Request + identity + receiver public key| S
  S -->|AuthZ check| AV
  S -->|Extract| SRC
  S -->|Write encrypted artifacts + manifest| SMS
  S -->|Delivery-time authZ check| AV
  S -->|Transfer via SSH-based protocol| R
  R -->|Write encrypted artifacts + manifest| RMS
```

## Option 2: Mage AI Embedded in Agency-Local FDE Adapter (Maximize Connector and Pipeline Capabilities)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant RMS as Receiver Mounted Storage<br/>(Encrypted Temporary Landing)
    participant R as Receiver Agent (Requestor)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
    participant CP as Central Control-plane Scheduler
  end
  box "Sender org"
    participant A as Agency-Local FDE Agent (Mage-enabled)
    participant SMS as Sender Mounted Storage<br/>(Encrypted Temporary Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    R->>CP: Submit authorized request + receiver public key
    CP->>A: Trigger agency-local adapter run (HTTPS)
    A->>A: Execute extraction pipeline using embedded Mage connectors
    A->>A: Compress + Encrypt to receiver public key
    A->>SMS: Write encrypted artifact(s) + manifest
    A->>AV: Delivery-time authorization check
    AV-->>A: Approved (or Denied)
    A->>R: Transfer encrypted artifacts and manifest via SSH protocol
    R->>RMS: Write encrypted artifacts and manifest to mounted storage
    CP->>CP: Track run status/metadata
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

  subgraph AgencyBoundary[Sender org]
    A3["FDE Agent (Mage-enabled extraction and FDE transfer)"]
    SRC3[(Agency Data Source)]
    SMS3[(Sender Mounted Storage<br/>Encrypted Temporary Staging)]
  end

  subgraph ReceiverSide[Receiver org]
    RMS3[(Receiver Mounted Storage<br/>Encrypted Temporary Landing + Manifest)]
    R3[Receiver Agent]
  end

  R3 --> AV3
  AV3 --> CP3
  CP3 --> A3
  A3 --> SRC3
  A3 --> SMS3
  A3 --> R3
  R3 --> RMS3
  R3 --> AV3
```

## Option 3: Mage AI as Control-plane Orchestrator + Adapter Security Wrapper

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant RMS as Receiver Mounted Storage<br/>(Encrypted Temporary Landing)
    participant R as Receiver Agent (Requestor)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
    participant M as Mage (Central Scheduler/Monitor)
  end
  box "Sender org"
    participant A as Agency-Local Agent (Extraction + FDE Wrapper)
    participant SMS as Sender Mounted Storage<br/>(Encrypted Temporary Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    R->>M: Submit authorized job request + receiver public key
    M->>A: Trigger extraction job (HTTPS) + receiver public key
    A->>A: Extract data from agency source system
    A->>A: Compress + Encrypt to receiver public key
    A->>SMS: Write encrypted artifact(s) + manifest
    A->>AV: Delivery-time authorization check
    AV-->>A: Approved (or Denied)
    A->>R: Transfer encrypted artifacts and manifest via SSH protocol
    R->>RMS: Write encrypted artifacts and manifest to mounted storage
    M->>M: Track status/metadata (scheduling/monitoring)
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

  subgraph SenderOrg[Sender org]
    A["Agency-Local Agent: Connectors and FDE Wrapper"]
    SRC[(Agency Data Source)]
    SMS[(Sender Mounted Storage<br/>Encrypted Temporary Staging)]
  end

  subgraph ReceiverOrg[Receiver org]
    RMS[(Receiver Mounted Storage<br/>Encrypted Temporary Landing + Manifest)]
    R[Receiver Agent]
  end

  R --> AV
  AV --> M
  M --> A
  A --> SRC
  A --> SMS
  A --> R
  R --> AV
  R --> RMS
```

## Option 4: Minimal Microservices POC (Fastest v0.03)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant R as Receiver (Minimal Service)
    participant RMS as Receiver Mounted Storage<br/>(Encrypted Temporary Landing)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
  end
  box "Sender org"
    participant S as Sender (Minimal Service)
    participant SRC as Source System
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    R->>S: Data request + receiver public key
    S->>SRC: Fetch or query requested data
    S->>S: Compress + Encrypt to receiver public key
    S->>AV: Delivery-time authorization check
    AV-->>S: Approved (or Denied)
    S-->>R: Transfer encrypted payload via SSH protocol
    R->>RMS: Write encrypted payload to mounted storage
  else Denied
    R-->>R: Denied / error response
  end
```

### Component diagram

```mermaid
flowchart LR
  subgraph DataPlane[Data-plane]
    R4[Receiver Minimal Service]
    AV4[Access Validation / Agreement Store]
    S4[Sender Minimal Service]
    SRC4[(Source System)]
    RMS4[(Receiver Mounted Storage<br/>Encrypted Temporary Landing)]
  end

  R4 -->|Authorization check| AV4
  R4 -->|Request + receiver public key| S4
  S4 -->|Extract| SRC4
  S4 -->|Encrypt + Transfer via SSH-based protocol| R4
  R4 -->|Write encrypted payload| RMS4
```
