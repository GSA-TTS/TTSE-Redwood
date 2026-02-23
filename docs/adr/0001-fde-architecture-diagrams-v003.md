# ADR 0001 Diagrams: FDE Architecture Options (v0.03)


## Option 1: Container-based Adapter Service (Cloud-agnostic)


### Sequence diagram


```mermaid
sequenceDiagram
 autonumber
 box "Receiver org"
   participant RMS as Receiver Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
   participant R as Receiver Agent (Requestor)
 end
 box "GSA control-plane"
   participant AV as Access Validation / Agreement Store
   participant CA as Keystore Certificates / Private CA
   participant SCA as SSH Certificates / SSH CA
 end
 box "Sender org"
   participant S as Sender Agent
   participant SMS as Sender Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
 end


 R->>CA: TLS identity validation (mTLS)
 R->>S: Data request + identity proof (HTTPS)
 S->>CA: TLS identity validation (mTLS)
 S->>AV: AuthZ check (HTTPS)
 AV-->>S: Authorized to deliver to receiver data store (or Denied)


 alt Authorized
   S->>S: Extract data from source system
   S->>S: Compress artifacts
   S->>SMS: Write artifact(s) (multipart if large)
   S->>SMS: Write manifest (metadata + checksums + file list)
   S->>R: Delivery attempt (HTTPS)
   R->>CA: TLS identity validation (mTLS)
   R->>AV: Delivery-time authZ check (HTTPS)
   AV-->>R: Approved (or Denied)
   S->>S: Generate SSH keypair (keep private key)
   S->>SCA: Submit SSH public key for signing (HTTPS)
   SCA-->>S: Issue SSH user certificate (time-limited)
   S->>R: Transfer artifacts and manifest via rsync over SSH encrypted in transit (GSA SSH certificate)
   R->>RMS: Write artifacts and manifest to mounted storage
 else Denied
   S-->>R: Denied / error response
 end
```


### Component diagram


```mermaid
flowchart LR
 subgraph ControlPlane[Control-plane]
   AV[Access Validation / Agreement Store]
   CA[Keystore Certificates / Private CA]
   SCA[SSH Certificates / SSH CA]
 end


 subgraph SenderOrg[Sender org]
   S[Sender Agent]
   SRC[(Agency Data Source)]
   SMS[(Sender Mounted Storage<br/>Encrypted at Rest, Platform-Managed)]
 end


 subgraph ReceiverOrg[Receiver org]
   RMS[(Receiver Mounted Storage<br/>Encrypted at Rest, Platform-Managed + Manifest)]
   R[Receiver Agent]
 end


 R -->|Request + identity HTTPS mTLS| S
 S -->|AuthZ check HTTPS mTLS| AV
 S -->|Extract| SRC
 S -->|Write artifacts + manifest| SMS
 S -->|Request short-lived SSH certificate| SCA
 S -->|Transfer via rsync over SSH encrypted in transit with SSH certificate| R
 R -->|Delivery-time authZ check HTTPS mTLS| AV
 R -->|Write artifacts + manifest| RMS
```


## Option 2: Mage AI Embedded in Agency-Local FDE Adapter (Maximize Connector and Pipeline Capabilities)


### Sequence diagram


```mermaid
sequenceDiagram
 autonumber
 box "Receiver org"
   participant RMS as Receiver Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
   participant R as Receiver Agent (Requestor)
 end
 box "GSA control-plane"
   participant AV as Access Validation / Agreement Store
   participant CP as Central Control-plane Scheduler
   participant CA as Keystore Certificates / Private CA
   participant SCA as SSH Certificates / SSH CA
 end
 box "Sender org"
   participant A as Agency-Local FDE Agent (Mage-enabled)
   participant SMS as Sender Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
 end


 R->>R: Prepare receiver endpoint
 R->>CA: TLS identity validation (mTLS)
 R->>AV: Request authorization for dataset + params (HTTPS)
 AV-->>R: Authorized to deliver to receiver data store (or Denied)


 alt Authorized
   R->>CA: TLS identity validation (mTLS)
   R->>CP: Submit authorized request (HTTPS)
   CP->>CA: TLS identity validation (mTLS)
   CP->>A: Trigger agency-local adapter run (HTTPS)
   A->>A: Execute extraction pipeline using embedded Mage connectors
   A->>A: Compress artifacts
   A->>SMS: Write artifact(s) + manifest
   A->>R: Delivery attempt (HTTPS)
   R->>CA: TLS identity validation (mTLS)
   R->>AV: Delivery-time authZ check (HTTPS)
   AV-->>R: Approved (or Denied)
   A->>A: Generate SSH keypair (keep private key)
   A->>SCA: Submit SSH public key for signing (HTTPS)
   SCA-->>A: Issue SSH user certificate (time-limited)
   A->>R: Transfer artifacts and manifest via rsync over SSH encrypted in transit (GSA SSH certificate)
   R->>RMS: Write artifacts and manifest to mounted storage
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
   CA3[Keystore Certificates / Private CA]
   SCA3[SSH Certificates / SSH CA]
 end


 subgraph AgencyBoundary[Sender org]
   A3["FDE Agent (Mage-enabled extraction and FDE transfer)"]
   SRC3[(Agency Data Source)]
   SMS3[(Sender Mounted Storage<br/>Encrypted at Rest, Platform-Managed)]
 end


 subgraph ReceiverSide[Receiver org]
   RMS3[(Receiver Mounted Storage<br/>Encrypted at Rest, Platform-Managed + Manifest)]
   R3[Receiver Agent]
 end


 R3 --> AV3
 AV3 --> CP3
 CP3 --> A3
 A3 --> SRC3
 A3 --> SMS3
 A3 --> SCA3
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
   participant RMS as Receiver Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
   participant R as Receiver Agent (Requestor)
 end
 box "GSA control-plane"
   participant AV as Access Validation / Agreement Store
   participant M as Mage (Central Scheduler/Monitor)
   participant CA as Keystore Certificates / Private CA
   participant SCA as SSH Certificates / SSH CA
 end
 box "Sender org"
   participant A as Agency-Local Agent (Extraction + FDE Wrapper)
   participant SMS as Sender Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
 end


 R->>CA: TLS identity validation (mTLS)
 R->>AV: Request authorization for dataset + params (HTTPS)
 AV-->>R: Authorized to deliver to receiver data store (or Denied)


 alt Authorized
   R->>CA: TLS identity validation (mTLS)
   R->>M: Submit authorized job request (HTTPS)
   M->>CA: TLS identity validation (mTLS)
   M->>A: Trigger extraction job (HTTPS)
   A->>A: Extract data from agency source system
   A->>A: Compress artifacts
   A->>SMS: Write artifact(s) + manifest
   A->>R: Delivery attempt (HTTPS)
   R->>CA: TLS identity validation (mTLS)
   R->>AV: Delivery-time authZ check (HTTPS)
   AV-->>R: Approved (or Denied)
   A->>A: Generate SSH keypair (keep private key)
   A->>SCA: Submit SSH public key for signing (HTTPS)
   SCA-->>A: Issue SSH user certificate (time-limited)
   A->>R: Transfer artifacts and manifest via rsync over SSH encrypted in transit (GSA SSH certificate)
   R->>RMS: Write artifacts and manifest to mounted storage
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
   CA[Keystore Certificates / Private CA]
   SCA[SSH Certificates / SSH CA]
 end


 subgraph SenderOrg[Sender org]
   A["Agency-Local Agent: Connectors and FDE Wrapper"]
   SRC[(Agency Data Source)]
   SMS[(Sender Mounted Storage<br/>Encrypted at Rest, Platform-Managed)]
 end


 subgraph ReceiverOrg[Receiver org]
   RMS[(Receiver Mounted Storage<br/>Encrypted at Rest, Platform-Managed + Manifest)]
   R[Receiver Agent]
 end


 R --> AV
 AV --> M
 M --> A
 A --> SRC
 A --> SMS
 A --> SCA
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
   participant RMS as Receiver Mounted Storage<br/>(Encrypted at Rest, Platform-Managed)
 end
 box "GSA control-plane"
   participant AV as Access Validation / Agreement Store
   participant CA as Keystore Certificates / Private CA
   participant SCA as SSH Certificates / SSH CA
 end
 box "Sender org"
   participant S as Sender (Minimal Service)
   participant SRC as Source System
 end


 R->>CA: TLS identity validation (mTLS)
 R->>AV: Request authorization for dataset + params (HTTPS)
 AV-->>R: Authorized to deliver to receiver data store (or Denied)


 alt Authorized
   R->>CA: TLS identity validation (mTLS)
   R->>S: Data request (HTTPS)
   S->>SRC: Fetch or query requested data
   S->>S: Compress payload
   S->>R: Delivery attempt (HTTPS)
   R->>CA: TLS identity validation (mTLS)
   R->>AV: Delivery-time authZ check (HTTPS)
   AV-->>R: Approved (or Denied)
   S->>S: Generate SSH keypair (keep private key)
   S->>SCA: Submit SSH public key for signing (HTTPS)
   SCA-->>S: Issue SSH user certificate (time-limited)
   S-->>R: Transfer payload via rsync over SSH encrypted in transit (GSA SSH certificate)
   R->>RMS: Write payload to mounted storage
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
   CA4[Keystore Certificates / Private CA]
   SCA4[SSH Certificates / SSH CA]
   S4[Sender Minimal Service]
   SRC4[(Source System)]
   RMS4[(Receiver Mounted Storage<br/>Encrypted at Rest, Platform-Managed)]
 end


 R4 -->|Authorization check| AV4
 R4 -->|Request| S4
 S4 -->|Extract| SRC4
 S4 -->|Request SSH certificate| SCA4
 S4 -->|Transfer via rsync over SSH encrypted in transit| R4
 R4 -->|Write payload| RMS4
```
