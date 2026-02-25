# ADR 003 Diagrams: MVP Architecture — FDE Agent V1 POC


## High-Level Component Diagram


```mermaid
flowchart LR
  subgraph ReceiverAgency["Section 1 — Receiver Agency"]
    RCFG["Data Request Config<br/>(requested data elements)"]
    RA["FDE Agent<br/>(Receiver Mode)"]
    R_SFTP["AWS Transfer Family<br/>SFTP Server<br/>(SSH Port 22)"]
    R_AUTH["SSH Public/Private<br/>Key Authentication"]
    RL[("S3 / EFS Landing<br/>(AWS SSE — Encrypted at Rest)")]
    RF[("Validated +<br/>Decompressed Files")]
    TS3[("Target S3 Storage<br/>(AWS SSE — Encrypted at Rest)")]
  end

  subgraph SenderAgency["Section 2 — Sender Agency"]
    SDB_A[(Database A<br/>e.g. PostgreSQL)]
    SDB_B[(Database B<br/>e.g. MySQL)]
    SA["FDE Agent<br/>(Sender Mode)"]
    SS[("S3 / EFS Staging<br/>(AWS SSE — Encrypted at Rest)")]
    SF[("Compressed Artifacts<br/>+ Manifest")]
    S_SFTP["AWS Transfer Family<br/>SFTP Server<br/>(SSH Port 22)"]
    S_AUTH["SSH Public/Private<br/>Key Authentication"]
  end

  subgraph AuditPlane["Audit Trail"]
    CLS["Central Logging Server<br/>(Splunk / Datadog)"]
  end

  %% Step 1: Receiver initiates data request
  RCFG -->|"1. Data request<br/>(data elements config)"| RA
  RA ==>|"2. Send data request"| R_SFTP
  R_AUTH -.->|Authenticate session| R_SFTP
  R_SFTP ==>|"Encrypted in Transit<br/>(SSH Port 22)"| S_SFTP
  S_AUTH -.->|Authenticate session| S_SFTP
  S_SFTP ==>|"3. Data request delivered"| SA

  %% Step 2: Sender extracts & ships requested data
  SDB_A -->|Data extraction| SA
  SDB_B -->|Data extraction| SA
  SA -->|"Compress (gzip)"| SS
  SS -->|Artifacts + Manifest| SF
  SF ==>|"4. SFTP put"| S_SFTP
  S_SFTP ==>|"Encrypted in Transit<br/>(SSH Port 22)"| R_SFTP
  R_SFTP ==>|"Files land in<br/>receiver storage"| RL
  RL -->|"Validate manifest checksums"| RA
  RA -->|"Decompress (gzip)"| RF
  RF -->|"Store extracted data"| TS3
  SA -->|"Send logs"| CLS
  RA -->|"Send logs"| CLS
```


---


## Sequence Diagram — End-to-End MVP Flow


```mermaid
sequenceDiagram
  autonumber
  box "Receiver Agency (Section 1)"
    participant TS3 as Target S3 Storage<br/>(AWS SSE Encrypted at Rest)
    participant RL as Receiver S3/EFS Landing<br/>(AWS SSE Encrypted at Rest)
    participant RA as Receiver Agent
    participant R_SFTP as Receiver SFTP Server<br/>(SSH Port 22)
  end
  box "Sender Agency (Section 2)"
    participant S_SFTP as Sender SFTP Server<br/>(SSH Port 22)
    participant SA as Sender Agent
    participant SDB as Source Database(s)
    participant SS as Sender S3/EFS Staging<br/>(AWS SSE Encrypted at Rest)
  end
  box "Audit"
    participant CLS as Central Logging Server<br/>(Splunk / Datadog)
  end

  Note over RA,SA: Step 1 — Receiver Agency Initiates Data Request
  RA->>CLS: Audit: data_request_initiated (transfer_session_id)
  RA->>RA: Load data request config (requested data elements)
  RA->>R_SFTP: Send data request
  R_SFTP->>S_SFTP: Encrypted in transit (SSH Port 22)
  S_SFTP->>SA: Data request delivered (data elements, filters, metadata)
  SA->>CLS: Audit: data_request_received (requested_elements)

  Note over SA,SS: Step 2 — Sender Agency Extracts & Stages Requested Data
  SA->>CLS: Audit: pipeline_start (transfer_session_id)
  SA->>SDB: Extract requested data elements from source
  SDB-->>SA: Return query results
  SA->>CLS: Audit: extract_data (metadata)

  SA->>SA: Compress artifacts (gzip)
  SA->>CLS: Audit: compress (original_bytes, compressed_bytes)

  SA->>SA: Build manifest.json (file list, SHA-256 checksums, metadata)
  SA->>CLS: Audit: manifest_created

  SA->>SS: Write compressed artifacts + manifest to staging
  Note over SS: AWS SSE encrypts at rest automatically<br/>(S3 SSE-S3/SSE-KMS or EFS KMS)

  Note over SA,R_SFTP: Step 3 — SFTP Transfer (SSH Encrypted in Transit)
  SA->>S_SFTP: Authenticate via SSH public/private key (port 22)
  S_SFTP-->>SA: SSH session established
  SA->>S_SFTP: SFTP put — upload compressed artifacts + manifest
  S_SFTP->>R_SFTP: Encrypted in transit (SSH Port 22)
  SA->>CLS: Audit: sftp_transfer (dest_host, bytes_sent)
  Note over S_SFTP,R_SFTP: Data encrypted in transit via SSH protocol<br/>indecipherable to any network listener

  R_SFTP->>RL: Files land in receiver S3/EFS storage
  Note over RL: AWS SSE encrypts at rest automatically

  Note over TS3,RA: Step 4 — Receiver Pipeline
  RA->>CLS: Audit: pipeline_start (transfer_session_id)
  RA->>RL: Read manifest.json from landing storage
  RA->>RA: Validate file checksums (SHA-256)
  RA->>CLS: Audit: validate_manifest (files_checked, all_passed)

  RA->>RL: Read compressed artifacts from landing storage
  RA->>RA: Decompress artifacts (gzip)
  RA->>CLS: Audit: decompress (decompressed_bytes)

  RA->>TS3: Store extracted data in target S3 (encrypted at rest)
  RA->>CLS: Audit: store_data (target_bucket, objects_stored)
  RA->>CLS: Audit: pipeline_complete (transfer_session_id)
```
