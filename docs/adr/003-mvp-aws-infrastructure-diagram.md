# ADR 003 Diagrams: MVP AWS Infrastructure — FDE Agent V1 POC

These diagrams map the logical MVP architecture from [003-mvp-architecture-diagram.md](./003-mvp-architecture-diagram.md) to concrete AWS services and infrastructure boundaries.


---


## AWS Infrastructure — Full View


```mermaid
flowchart TB
  subgraph AWS["☁️ AWS Cloud"]

    subgraph SharedServices["Shared Services (per agency account)"]
      ECR["Amazon ECR<br/>FDE Agent Container Image Registry<br/>🔒 Image scanning + encryption"]
      SSM["AWS Systems Manager<br/>Parameter Store<br/>(task config, feature flags,<br/>endpoint URLs, non-secret params)"]
    end

    subgraph ReceiverVPC["Receiver Agency VPC"]

      subgraph R_Private["Private Subnets"]
        R_ECS["Amazon ECS / Fargate<br/>FDE Agent (Receiver Mode)<br/>🔑 SSH Private Key in Secrets Manager"]
        R_RDS_Read["Amazon RDS<br/>(read access — future)"]
      end

      subgraph R_Storage["Storage Layer"]
        R_S3_Landing["Amazon S3<br/>Landing Bucket<br/>🔒 SSE-S3 / SSE-KMS"]
        R_EFS_Landing["Amazon EFS<br/>Landing Mount<br/>🔒 KMS Encryption"]
        R_S3_Target["Amazon S3<br/>Target Bucket<br/>🔒 SSE-S3 / SSE-KMS"]
      end

      R_TF["AWS Transfer Family<br/>SFTP Endpoint<br/>(SSH Port 22)<br/>📋 Authorized Keys<br/>→ backed by S3 or EFS"]

      subgraph R_Security["Security & Identity"]
        R_SM["AWS Secrets Manager<br/>(SSH Private Key, DB creds)"]
        R_KMS["AWS KMS<br/>(Encryption Keys)"]
        R_SG["Security Group<br/>Inbound: TCP 22<br/>from Sender Agency CIDR"]
      end

      subgraph R_Observability["Observability"]
        R_CW["Amazon CloudWatch<br/>Logs & Metrics"]
      end
    end

    subgraph SenderVPC["Sender Agency VPC"]

      subgraph S_Private["Private Subnets"]
        S_ECS["Amazon ECS / Fargate<br/>FDE Agent (Sender Mode)<br/>🔑 SSH Private Key in Secrets Manager"]
      end

      subgraph S_DataSources["Data Sources"]
        S_RDS_A["Amazon RDS<br/>PostgreSQL"]
        S_RDS_B["Amazon RDS<br/>MySQL"]
      end

      subgraph S_Storage["Storage Layer"]
        S_S3_Staging["Amazon S3<br/>Staging Bucket<br/>(Compressed Artifacts + Manifest)<br/>🔒 SSE-S3 / SSE-KMS"]
        S_EFS_Staging["Amazon EFS<br/>Staging Mount<br/>🔒 KMS Encryption"]
      end

      S_TF["AWS Transfer Family<br/>SFTP Endpoint<br/>(SSH Port 22)<br/>📋 Authorized Keys<br/>→ backed by S3 or EFS"]

      subgraph S_Security["Security & Identity"]
        S_SM["AWS Secrets Manager<br/>(SSH Private Key, DB creds)"]
        S_KMS["AWS KMS<br/>(Encryption Keys)"]
        S_SG["Security Group<br/>Inbound: TCP 22<br/>from Receiver Agency CIDR"]
      end

      subgraph S_Observability["Observability"]
        S_CW["Amazon CloudWatch<br/>Logs & Metrics"]
      end
    end

    subgraph AuditPlane["Centralized Audit"]
      KDF["Amazon Kinesis Data Firehose<br/>(log delivery stream)"]
      CLS["Splunk / Datadog<br/>Central Logging"]
    end

  end

  %% ECR → ECS (image pull)
  ECR -.->|"Pull container image"| R_ECS
  ECR -.->|"Pull container image"| S_ECS

  %% SSM → ECS (task config)
  SSM -.->|"Read task parameters<br/>(endpoints, config flags)"| R_ECS
  SSM -.->|"Read task parameters<br/>(endpoints, config flags)"| S_ECS

  %% Agent → Secrets Manager
  R_SM -.->|"Retrieve SSH key / DB creds"| R_ECS
  S_SM -.->|"Retrieve SSH key / DB creds"| S_ECS

  %% KMS for storage encryption
  R_KMS -.->|"Encrypt/Decrypt"| R_S3_Landing
  R_KMS -.->|"Encrypt/Decrypt"| R_EFS_Landing
  R_KMS -.->|"Encrypt/Decrypt"| R_S3_Target
  S_KMS -.->|"Encrypt/Decrypt"| S_S3_Staging
  S_KMS -.->|"Encrypt/Decrypt"| S_EFS_Staging

  %% Transfer Family backend storage
  R_TF -->|"Backend storage"| R_S3_Landing
  R_TF -->|"Backend storage"| R_EFS_Landing
  S_TF -->|"Backend storage"| S_S3_Staging

  %% Step 1: Receiver agent → Sender SFTP
  R_ECS ==>|"1. SFTP put data request<br/>(SSH Port 22)"| S_TF
  S_TF ==>|"2. Request delivered"| S_ECS

  %% Step 2: Sender extracts & stages
  S_RDS_A -->|"SQL extraction"| S_ECS
  S_RDS_B -->|"SQL extraction"| S_ECS
  S_ECS -->|"gzip + manifest.json"| S_S3_Staging

  %% Step 3: Sender agent → Receiver SFTP
  S_ECS ==>|"3. SFTP put artifacts<br/>(SSH Port 22)"| R_TF

  %% Step 4: Receiver pipeline
  R_S3_Landing -->|"Read manifest + artifacts"| R_ECS
  R_ECS -->|"Validated + decompressed data"| R_S3_Target

  %% Observability → Central Audit
  R_ECS -->|"Audit events"| R_CW
  S_ECS -->|"Audit events"| S_CW
  R_CW -->|"Stream"| KDF
  S_CW -->|"Stream"| KDF
  KDF -->|"Deliver"| CLS
```


---


## AWS Network & Security Diagram


```mermaid
flowchart LR
  subgraph Internet["Public Internet"]
    direction TB
    IGW_R["Internet Gateway<br/>(Receiver VPC)"]
    IGW_S["Internet Gateway<br/>(Sender VPC)"]
  end

  subgraph ReceiverVPC["Receiver Agency VPC<br/>10.1.0.0/16"]
    subgraph R_PubSub["Public Subnet(s)"]
      R_NAT["NAT Gateway"]
      R_TF_ENI["Transfer Family<br/>VPC Endpoint ENI<br/>(or public endpoint)"]
    end
    subgraph R_PriSub["Private Subnet(s)"]
      R_ECS["ECS / Fargate Tasks<br/>FDE Agent (Receiver)"]
      R_S3_EP["S3 VPC Endpoint<br/>(Gateway)"]
      R_EFS_MT["EFS Mount Target(s)<br/>(private subnet)"]
    end
    R_S3_BKT["S3 Bucket Backend<br/>(Landing / Target)"]
    R_SG["🛡️ Security Group<br/>Inbound TCP 22: Sender CIDR<br/>Outbound TCP 22: Sender SFTP<br/>Outbound TCP 443: AWS APIs"]
  end

  subgraph SenderVPC["Sender Agency VPC<br/>10.2.0.0/16"]
    subgraph S_PubSub["Public Subnet(s)"]
      S_NAT["NAT Gateway"]
      S_TF_ENI["Transfer Family<br/>VPC Endpoint ENI<br/>(or public endpoint)"]
    end
    subgraph S_PriSub["Private Subnet(s)"]
      S_ECS["ECS / Fargate Tasks<br/>FDE Agent (Sender)"]
      S_RDS["RDS Instances<br/>(PostgreSQL / MySQL)"]
      S_S3_EP["S3 VPC Endpoint<br/>(Gateway)"]
      S_EFS_MT["EFS Mount Target(s)<br/>(private subnet)"]
    end
    S_S3_BKT["S3 Bucket Backend<br/>(Staging)"]
    S_SG["🛡️ Security Group<br/>Inbound TCP 22: Receiver CIDR<br/>Outbound TCP 22: Receiver SFTP<br/>Outbound TCP 443: AWS APIs"]
  end

  %% Internet connectivity
  R_NAT <-->|"Outbound traffic"| IGW_R
  S_NAT <-->|"Outbound traffic"| IGW_S
  R_TF_ENI <-->|"Inbound SFTP"| IGW_R
  S_TF_ENI <-->|"Inbound SFTP"| IGW_S

  %% Cross-agency SFTP (over public internet)
  R_ECS ==>|"SFTP client → Sender SFTP<br/>(SSH Port 22 via NAT)"| R_NAT
  IGW_R ==>|"SSH Port 22"| IGW_S
  IGW_S ==>|"Route to Transfer Family"| S_TF_ENI

  S_ECS ==>|"SFTP client → Receiver SFTP<br/>(SSH Port 22 via NAT)"| S_NAT
  IGW_S ==>|"SSH Port 22"| IGW_R
  IGW_R ==>|"Route to Transfer Family"| R_TF_ENI

  %% Private access to S3
  R_ECS -.->|"S3 API via endpoint"| R_S3_EP
  S_ECS -.->|"S3 API via endpoint"| S_S3_EP
  R_S3_EP -.->|"Route to S3"| R_S3_BKT
  S_S3_EP -.->|"Route to S3"| S_S3_BKT

  %% Optional backend path for Transfer Family and ECS
  R_TF_ENI -.->|"Optional backend: S3"| R_S3_BKT
  S_TF_ENI -.->|"Optional backend: S3"| S_S3_BKT
  R_TF_ENI -.->|"Optional backend mount"| R_EFS_MT
  S_TF_ENI -.->|"Optional backend mount"| S_EFS_MT
  R_ECS -.->|"Optional NFS mount (2049)"| R_EFS_MT
  S_ECS -.->|"Optional NFS mount (2049)"| S_EFS_MT

  %% Agent → RDS
  S_ECS -->|"SQL (private)"| S_RDS
```


---


## AWS Service Mapping

| Logical Component (from 003 diagrams) | AWS Service | Key Configuration | Cost Dimension |
|---|---|---|---|
| FDE Agent container image | **Amazon ECR** | Private repository; image scanning enabled; encrypted at rest | Storage (GB/month) + data transfer out |
| FDE Agent (Sender / Receiver) | **Amazon ECS on Fargate** | Task in private subnet; pulls image from ECR; IAM task role for S3, SSM, Secrets Manager, CloudWatch | vCPU-hours + GB-memory-hours per task |
| Task configuration & parameters | **AWS Systems Manager Parameter Store** | Endpoint URLs, feature flags, non-secret config injected as env vars at task start | Standard params: free; Advanced params: per param/month |
| AWS Transfer Family SFTP Server | **AWS Transfer Family** (SFTP protocol) | Public or VPC endpoint; SSH authorized keys; backend = S3 bucket or EFS mount | Per protocol per hour + data upload (GB) |
| S3 Landing / Staging / Target | **Amazon S3** | Bucket default encryption: SSE-S3 or SSE-KMS; bucket policy restricts access to agent role + Transfer Family | Storage (GB/month) + requests + data transfer |
| EFS Landing / Staging (alternative) | **Amazon EFS** | Encrypted at rest via KMS; mounted to Fargate tasks and/or Transfer Family | Storage (GB/month) by class + throughput |
| Source Databases | **Amazon RDS** (PostgreSQL, MySQL) | Private subnet; security group allows inbound from agent tasks only | Instance hours + storage + I/O |
| SSH Private Key / DB credentials | **AWS Secrets Manager** | Agent retrieves at task start; automatic rotation (production) | Per secret/month + per 10K API calls |
| Encryption keys | **AWS KMS** | Customer-managed or AWS-managed keys for S3 SSE-KMS, EFS, Secrets Manager, ECR | Per key/month + per 10K API requests |
| Security Groups | **VPC Security Groups** | Inbound TCP 22 from remote agency CIDR; outbound TCP 22 to remote SFTP; outbound 443 for AWS APIs | No additional charge |
| Network (outbound) | **NAT Gateway** | Agent SFTP client traffic exits via NAT → Internet Gateway | Per hour + per GB processed |
| Network (S3 access) | **S3 VPC Gateway Endpoint** | Keeps S3 traffic off the public internet | No additional charge |
| Agent logs | **Amazon CloudWatch Logs** | Structured audit events from ECS tasks | Ingestion (GB) + storage (GB/month) |
| Log delivery | **Amazon Kinesis Data Firehose** | Streams CloudWatch logs to Splunk / Datadog | Per GB ingested |
| Central Logging | **Splunk / Datadog** | Receives audit events via Firehose delivery stream | Per vendor licensing / GB ingested |


---


## IAM Roles & Policies (Summary)


```mermaid
flowchart TD
  subgraph IAM["AWS IAM"]
    TaskExecRole["ECS Task Execution Role<br/>(pull image + inject secrets)"]
    TaskRole["ECS Task Role<br/>(FDE Agent runtime)"]
    TFRole["Transfer Family<br/>Service Role"]
  end

  subgraph Permissions["Policy Attachments"]
    P_ECR["ecr:GetAuthorizationToken / ecr:BatchGetImage<br/>on FDE agent repository"]
    P_S3["s3:GetObject / s3:PutObject<br/>on staging, landing, target buckets"]
    P_SM["secretsmanager:GetSecretValue<br/>on SSH private key + DB credential secrets"]
    P_SSM["ssm:GetParameter / ssm:GetParameters<br/>on task config parameter paths"]
    P_KMS["kms:Decrypt / kms:GenerateDataKey<br/>on encryption keys"]
    P_CW["logs:PutLogEvents / logs:CreateLogStream<br/>on CloudWatch log groups"]
    P_EFS["elasticfilesystem:ClientMount / ClientWrite<br/>on EFS access points"]
    P_TF_S3["s3:PutObject / s3:GetObject<br/>on Transfer Family backend bucket"]
  end

  TaskExecRole --> P_ECR
  TaskExecRole --> P_SM
  TaskExecRole --> P_SSM
  TaskExecRole --> P_CW
  TaskRole --> P_S3
  TaskRole --> P_SM
  TaskRole --> P_SSM
  TaskRole --> P_KMS
  TaskRole --> P_CW
  TaskRole --> P_EFS
  TFRole --> P_TF_S3
  TFRole --> P_KMS
```


---


## Encryption Layers — AWS Service View


```mermaid
flowchart LR
  subgraph InTransit["🔐 Encryption in Transit"]
    SSH["SSH Protocol (Port 22)<br/>SFTP sessions between<br/>Agent ↔ Transfer Family"]
    TLS["TLS 1.2+<br/>Agent ↔ AWS APIs<br/>(S3, Secrets Manager, KMS, CloudWatch)"]
  end

  subgraph AtRest["🔒 Encryption at Rest"]
    subgraph S3Enc["Amazon S3"]
      SSE_S3["SSE-S3<br/>(AES-256, AWS-managed key)"]
      SSE_KMS["SSE-KMS<br/>(Customer or AWS-managed CMK)"]
    end
    subgraph EFSEnc["Amazon EFS"]
      EFS_KMS["KMS-based encryption<br/>(configured at file-system creation)"]
    end
    subgraph SMEnc["Secrets Manager"]
      SM_KMS["KMS envelope encryption<br/>(for stored SSH keys)"]
    end
  end

  subgraph KeyMgmt["🔑 Key Management"]
    KMS["AWS KMS<br/>- S3 bucket keys (SSE-KMS)<br/>- EFS encryption key<br/>- Secrets Manager envelope key"]
  end

  KMS -.-> SSE_KMS
  KMS -.-> EFS_KMS
  KMS -.-> SM_KMS
```


---


## ECS Task Bootstrap — ECR, SSM & Secrets Manager


```mermaid
sequenceDiagram
  autonumber
  participant ECR as Amazon ECR<br/>(Image Registry)
  participant ECS as Amazon ECS<br/>(Task Scheduler)
  participant Fargate as Fargate Task<br/>(FDE Agent)
  participant SSM as SSM Parameter Store<br/>(Task Config)
  participant SM as Secrets Manager<br/>(SSH Key, DB Creds)
  participant KMS as AWS KMS<br/>(Decryption)

  ECS->>ECR: Pull FDE agent container image
  ECR-->>ECS: Image layers (encrypted at rest, decrypted on pull)
  ECS->>Fargate: Launch task with image

  Note over Fargate,SM: Task Execution Role injects secrets + config as env vars
  Fargate->>SSM: GetParameters (endpoint URLs, feature flags, config)
  SSM-->>Fargate: Parameter values (plaintext)
  Fargate->>SM: GetSecretValue (SSH private key)
  SM->>KMS: Decrypt envelope key
  KMS-->>SM: Decrypted data key
  SM-->>Fargate: SSH private key (plaintext, in-memory only)
  Fargate->>SM: GetSecretValue (DB credentials)
  SM->>KMS: Decrypt envelope key
  KMS-->>SM: Decrypted data key
  SM-->>Fargate: DB credentials (plaintext, in-memory only)

  Note over Fargate: Agent ready — begins pipeline execution
```



