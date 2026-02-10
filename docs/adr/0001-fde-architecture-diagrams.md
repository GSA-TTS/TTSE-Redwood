# ADR 0001 Diagrams: FDE Architecture Options (v0.02)

## Option 1: Container-based Adapter Service (Cloud-agnostic)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant R as Receiver Adapter (Requestor)
    participant ROS as Receiver Object Store (Encrypted Handoff)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
  end
  box "Sender org"
    participant S as Sender Adapter
    participant SOS as Sender Object Store (Encrypted Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>S: Data request + identity proof + receiver public key
  S->>AV: Validate request identity + agreement/policy for dataset + receiver acceptance
  AV-->>S: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    S->>S: Extract data from source system
    S->>S: Compress + Encrypt to receiver public key
    S->>SOS: Upload encrypted artifact(s) (multipart if large)
    S->>SOS: Write manifest (metadata + checksums + file list)
    S->>AV: Delivery-time authorization check (sender -> receiver store)
    AV-->>S: Approved (or Denied)
    S->>ROS: Push encrypted artifact(s) + manifest
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
    S[Sender Adapter]
    SRC[(Agency Data Source)]
    SOS[(Sender Object Store Encrypted Staging)]
  end

  subgraph ReceiverOrg[Receiver org]
    R[Receiver Adapter]
    ROS[(Receiver Object Store Encrypted Handoff + Manifest)]
  end

  R -->|Request + identity + receiver public key| S
  S -->|AuthZ check| AV
  S -->|Extract| SRC
  S -->|Write encrypted artifacts + manifest| SOS
  S -->|Push artifacts + manifest| ROS
  R -->|Receive encrypted artifacts + manifest| ROS
```

## Option 2: Mage AI Embedded in Agency-Local FDE Adapter (Maximize Connector and Pipeline Capabilities)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant R as Receiver Adapter (Requestor)
    participant ROS as Receiver Object Store (Encrypted Handoff)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
    participant CP as Central Control-plane Scheduler
  end
  box "Sender org"
    participant A as Agency-Local FDE Adapter (Mage-enabled)
    participant SOS as Sender Object Store (Encrypted Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    R->>CP: Submit authorized request + receiver public key
    CP->>A: Trigger agency-local adapter run (HTTPS)
    A->>A: Execute extraction pipeline using embedded Mage connectors
    A->>A: Compress + Encrypt to receiver public key
    A->>SOS: Upload encrypted artifact(s) + manifest
    A->>AV: Delivery-time authorization check (sender -> receiver store)
    AV-->>A: Approved (or Denied)
    A->>ROS: Push encrypted artifact(s) + manifest
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
    A3["FDE Adapter (Mage-enabled extraction and FDE transfer)"]
    SRC3[(Agency Data Source)]
    SOS3[(Sender Object Store Encrypted Staging)]
  end

  subgraph ReceiverSide[Receiver org]
    R3[Receiver Adapter]
    ROS3[(Receiver Object Store Encrypted Handoff + Manifest)]
  end

  R3 --> AV3
  AV3 --> CP3
  CP3 --> A3
  A3 --> SRC3
  A3 --> SOS3
  A3 --> ROS3
  R3 --> ROS3
```

## Option 3: Mage AI as Control-plane Orchestrator + Adapter Security Wrapper

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant R as Receiver Adapter (Requestor)
    participant ROS as Receiver Object Store (Encrypted Handoff)
  end
  box "GSA control-plane"
    participant AV as Access Validation / Agreement Store
    participant M as Mage (Central Scheduler/Monitor)
  end
  box "Sender org"
    participant A as Agency-Local Adapter (Extraction + FDE Wrapper)
    participant SOS as Sender Object Store (Encrypted Staging)
  end

  R->>R: Generate ephemeral keypair (keep private key)
  R->>AV: Request authorization for dataset + params
  AV-->>R: Authorized to deliver to receiver data store (or Denied)

  alt Authorized
    R->>M: Submit authorized job request + receiver public key
    M->>A: Trigger extraction job (HTTPS) + receiver public key
    A->>A: Extract data from agency source system
    A->>A: Compress + Encrypt to receiver public key
    A->>SOS: Upload encrypted artifact(s) + manifest
    A->>AV: Delivery-time authorization check (sender -> receiver store)
    AV-->>A: Approved (or Denied)
    A->>ROS: Push encrypted artifact(s) + manifest
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
    A["Agency-Local Adapter: Connectors and FDE Wrapper"]
    SRC[(Agency Data Source)]
    SOS[(Sender Object Store Encrypted Staging)]
  end

  subgraph ReceiverOrg[Receiver org]
    R[Receiver Adapter]
    ROS[(Receiver Object Store Encrypted Handoff + Manifest)]
  end

  R --> AV
  AV --> M
  M --> A
  A --> SRC
  A --> SOS
  A --> ROS
  R --> ROS
```

## Option 4: Minimal Microservices POC (Fastest v0.02)

### Sequence diagram

```mermaid
sequenceDiagram
  autonumber
  box "Receiver org"
    participant R as Receiver (Minimal Service)
    participant ROS as Receiver Object Store (Encrypted Handoff)
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
    S->>AV: Delivery-time authorization check (sender -> receiver store)
    AV-->>S: Approved (or Denied)
    S-->>ROS: Push encrypted payload (HTTPS)
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
    ROS4[(Receiver Object Store Encrypted Handoff)]
  end

  R4 -->|Authorization check| AV4
  R4 -->|Request + receiver public key| S4
  S4 -->|Extract| SRC4
  S4 -->|Encrypt + Push HTTPS| ROS4
```
