# Redwood Data Agent Deployment Guide (Sender and Receiver)

This guide is for third-party agencies deploying the Redwood Data Agent container image using AWS infrastructure.

The same image supports two roles:

- Sender: reads outgoing files from object storage, prepares transfer artifacts, and runs sender workflow.
- Receiver: reads transfer artifacts from landing storage, validates/decompresses, and stores to target storage.

## 1. Deployment Model

Deploy the image as a long-running container workload on AWS (for example, ECS, EKS, or Elastic Beanstalk).

Runtime behavior:

- Starts once and runs continuously.
- Executes workflow on a 5-minute scheduler loop.
- Writes structured logs to stdout/stderr.
- Handles SIGTERM for graceful shutdown.

## 2. AWS Requirements

Your AWS environment must provide:

- Container runtime (ECS, EKS, Elastic Beanstalk, or equivalent) capable of running the published image.
- S3 buckets for staging (sender), landing (receiver), and target (receiver) storage.
- IAM role with permissions to read/write required S3 buckets and access AWS Secrets Manager.
- AWS Secrets Manager secret containing SFTP credentials (for sender mode).
- CloudWatch or equivalent log collection from container stdout/stderr.

Notes:

- The implementation uses AWS S3 API via `boto3` and AWS Secrets Manager for credential management.
- Ensure the IAM role has least-privilege access to required buckets and the secrets manager secret.

## 3. Required Environment Variables

Set these variables in the container runtime.

Common:

- `AGENT_MODE`: `sender` or `receiver`.
- `AGENCY`: agency code for this deployment (required).
- `TENANT`: default `tts`; used to derive default SFTP secret name when `SFTP_SECRETS_MANAGER_NAME` is not set. Example default secret: `{TENANT}-core-{ENVIRONMENT}-redwood-sftp-credentials`.
- `ENVIRONMENT`: default `development`; used in storage bucket naming and default SFTP secret naming. This value must match your deployed AWS resource naming (commonly `dev`, `staging`, or `prod`). Example sender bucket pattern: `tts-core-{ENVIRONMENT}-{AGENCY}-data-staging`.
- `AWS_REGION`: default `us-east-1`.
- `LOG_LEVEL`: default `INFO`; supported values are Python standard levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- `TRANSFER_SESSION_ID`: optional override for advanced operations. Recommended for agency deployments: do not set this value and allow auto-generation so each run gets a unique correlation ID. Set explicitly only for controlled replay/troubleshooting scenarios where you need a known fixed session ID.

Sender-only:

- `SFTP_ENDPOINTS`: comma-separated endpoints; required in sender mode.
- `SFTP_SECRETS_MANAGER_NAME`: optional; default derived as `{TENANT}-core-{ENVIRONMENT}-redwood-sftp-credentials`.
- `SENDER_INPUT_MODE`: sender input mode selector. Supported values: `file`, `query`. Default/fallback is `file`.
- `SENDER_QUERY_INPUT_JSON`: required when `SENDER_INPUT_MODE=query`; JSON payload with `template_id`, `params`, optional `row_limit`, and optional `timeout_seconds`.
- `MAX_QUERY_ROW_LIMIT`: optional global query row cap; defaults to `1000000` when not set.
- `MAX_QUERY_TIMEOUT_SECONDS`: optional global query timeout cap in seconds; defaults to `600` when not set.

Query-template allow-list note:

- Allowed query templates are maintained in `src/redwood_dataagent/query_templates.py`.
- This allow-list is expected to be expanded or modified as required when onboarding additional agencies.

Receiver-only:

- No additional required variables beyond common variables.

## 4. Storage Expectations

Bucket names are derived by code using:

- Sender staging: `tts-core-{environment}-{agency}-data-staging`
- Receiver landing: `tts-core-{environment}-{agency}-data-landing`
- Receiver target: `tts-core-{environment}-{agency}-data-target`

Key path conventions used by workflows:

- Sender scan prefix: `outgoing/` in the sender staging bucket (`tts-core-{environment}-{agency}-data-staging`). Agencies should place files they want to share in this prefix for sender processing.
- Sender transfer artifacts: `transfers/{transfer_session_id}/...` in the sender staging bucket (`tts-core-{environment}-{agency}-data-staging`). The adapter writes generated transfer artifacts to this prefix.
- Receiver marker/idempotency objects under transfer prefixes

Ensure the workload identity can perform read/write/list/head operations on required buckets and prefixes.

## 5. Minimal IAM/Access Permissions

Grant the workload identity least-privilege access to only required buckets/prefixes.

Sender typically needs:

- Read/list from sender outgoing/staging prefixes.
- Write for generated artifacts and sender marker objects.

Receiver typically needs:

- Read/list from landing bucket transfer prefixes.
- Write to target bucket extracted prefixes.
- Read/write for receiver idempotency markers.

## 6. Secrets Requirements

If sender mode uses SFTP integration, provision secret material expected by your configuration path.

SFTP secret payload must include:

- `user`
- `private-key`
- `public-key`

Store and mount these using your platform-native secret manager and workload identity policy.

## 6.1 Query Mode (Ibis Adapter) Requirements

When deploying with `SENDER_INPUT_MODE=query`:

- Source database must be accessible from the container's network
- RDS credentials should be injected as environment variables from a deployment-specific secret source configured by your platform
- Set `DB_ENGINE=<engine>` (default is `postgres`; current implementation target)
- The following environment variables must be present (provided by your deployment configuration):
  - `DB_HOST` — RDS endpoint hostname
  - `DB_PORT` — RDS port (default: `5432`)
  - `DB_NAME` — database name
  - `DB_USERNAME` — database user
  - `DB_PASSWORD` — database password

Future database expansion (high level):

- Current implementation target is `DB_ENGINE=postgres`.
- To onboard a different database engine, deployment updates will be required for:
  - Engine-specific connector configuration (`DB_ENGINE` value)
  - Engine-specific connection settings/secrets (host/port/auth fields as required)
  - Container dependencies/drivers needed by that engine

Dependency/install note for future engines:

- Current package dependency includes `ibis-framework[postgres]` for the active `postgres` backend.
- If a new database backend is added, update package dependencies to include that backend's Ibis extra (or equivalent driver set).
- If backend dependencies are refactored into optional install groups, update container install commands (for example in Docker build and CI install steps) to install the matching group.

- Set `SENDER_QUERY_INPUT_JSON` to a JSON payload with your query contract
- Ensure the template ID in the contract is allow-listed in `src/redwood_dataagent/query_templates.py`
- Query results are staged to S3 under `query/{transfer_session_id}/{template_id}_results.csv`
- Query mode writes a success marker after a completed run; repeated runs with the same query criteria and source DB context are skipped

See the [README](../README.md) for detailed query mode architecture, contract structure, and examples.

Integration with the existing sender transfer pipeline (policy check, compression, manifest generation, and transfer artifact staging) will be addressed in RED-74/RED-93.

## 7. Deploy as Sender

Set:

- `AGENT_MODE=sender`
- `AGENCY=<sender_agency_code>`
- `ENVIRONMENT=<dev|staging|prod>`
- `TENANT=<tenant>`
- `AWS_REGION=<region>`
- `LOG_LEVEL=INFO` (or as needed)
- `SFTP_ENDPOINTS=<endpoint1,endpoint2,...>`
- `SFTP_SECRETS_MANAGER_NAME=<secret_name>` (optional override)
- `SENDER_INPUT_MODE=file` (recommended default; set to `query` when query extraction is enabled)
- `DB_ENGINE=<engine>` (required when `SENDER_INPUT_MODE=query`; default is `postgres`)
- `SENDER_QUERY_INPUT_JSON=<json payload>` (required when `SENDER_INPUT_MODE=query`)
- `MAX_QUERY_ROW_LIMIT=<int>` (optional global cap; defaults to `1000000`)
- `MAX_QUERY_TIMEOUT_SECONDS=<int>` (optional global cap; defaults to `600`)

Example container run:

```bash
docker run --rm \
  -e AGENT_MODE=sender \
  -e AGENCY=dot \
  -e TENANT=tts \
  -e ENVIRONMENT=dev \
  -e AWS_REGION=us-east-1 \
  -e LOG_LEVEL=INFO \
  -e SFTP_ENDPOINTS=sftp.example.org \
  -e SENDER_INPUT_MODE=file \
  ghcr.io/<org>/<image>:<tag>
```

## 8. Deploy as Receiver

Set:

- `AGENT_MODE=receiver`
- `AGENCY=<receiver_agency_code>`
- `ENVIRONMENT=<dev|staging|prod>`
- `TENANT=<tenant>`
- `AWS_REGION=<region>`
- `LOG_LEVEL=INFO` (or as needed)

Example container run:

```bash
docker run --rm \
  -e AGENT_MODE=receiver \
  -e AGENCY=gsa \
  -e TENANT=tts \
  -e ENVIRONMENT=dev \
  -e AWS_REGION=us-east-1 \
  -e LOG_LEVEL=INFO \
  ghcr.io/<org>/<image>:<tag>
```

## 9. EKS (Kubernetes on AWS) Example (Mode-Specific)

Use one deployment per mode (sender and receiver), each with its own service account, IAM role, and environment variables.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redwood-agent-sender
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redwood-agent-sender
  template:
    metadata:
      labels:
        app: redwood-agent-sender
    spec:
      serviceAccountName: redwood-agent-sender
      containers:
        - name: redwood-agent
          image: ghcr.io/<org>/<image>:<tag>
          env:
            - name: AGENT_MODE
              value: sender
            - name: AGENCY
              value: dot
            - name: TENANT
              value: tts
            - name: ENVIRONMENT
              value: dev
            - name: AWS_REGION
              value: us-east-1
            - name: LOG_LEVEL
              value: INFO
            - name: SFTP_ENDPOINTS
              value: sftp.example.org
            - name: SENDER_INPUT_MODE
              value: file
```

## 10. Validation Checklist After Deployment

For both sender and receiver:

- Container starts successfully.
- Startup log appears in central logging system.
- Periodic scheduler execution logs appear every 5 minutes.
- No configuration validation errors on startup.

Example startup/scheduler logs to look for (sanitized from real runs; host/IP and IAM role values are masked):

```text
Sender startup example
[masked-host].ec2.internal
Starting Redwood Data Agent...
[sender] Redwood Data Agent initializing
[sender] Starting 5-minute scheduler loop
[sender][20260429-155625-6f89d35e] Executing agent workflow
[sender][20260429-155625-6f89d35e] Scanning sender directory for new files
Found credentials from IAM Role: example-development-iam-role
[sender][20260429-155625-6f89d35e] No new file read. Exiting sender workflow (idempotent).
[sender][20260429-155625-6f89d35e] Agent workflow completed, sleeping 300s until next run

Receiver startup example
[masked-host].ec2.internal
Starting Redwood Data Agent...
[receiver] Redwood Data Agent initializing
[receiver] Starting 5-minute scheduler loop
[receiver][20260429-155625-5f845992] Executing agent workflow
```

Sender checks:

- Agent can list and read objects under the sender staging bucket `outgoing/` prefix.
- Transfer artifacts are written to expected `transfers/{session}/` path.

Example sender logs to look for:

```text
[masked-host].ec2.internal
Found credentials from IAM Role: example-development-iam-role
[sender][20260428-173155-ac828e63] Executing agent workflow
[sender][20260428-173155-ac828e63] Scanning sender directory for new files
[sender][20260428-173155-ac828e63] Found 1 file(s) to process in sender directory
[sender][20260428-173155-ac828e63] Processing file: test-file.json
[sender][20260428-173155-ac828e63] pipeline_start: success
[sender][20260428-173155-ac828e63] File read successfully: test-file.json
[sender][20260428-173155-ac828e63] extract_data: success
[sender][20260428-173155-ac828e63] policy_check: success
[sender][20260428-173155-ac828e63] compress: success
[sender][20260428-173155-ac828e63] manifest_created: success
[sender][20260428-173155-ac828e63] Staged artifact to S3: transfer.tar.gz
[sender][20260428-173155-ac828e63] Staged artifact to S3: manifest.json
[sender][20260428-173155-ac828e63] sftp_transfer_start: success
[sender][20260428-173155-ac828e63] Uploaded artifact to SFTP: transfer.tar.gz
[sender][20260428-173155-ac828e63] Uploaded artifact to SFTP: manifest.json
[sender][20260428-173155-ac828e63] sftp_transfer_complete: success
[sender][20260428-173155-ac828e63] Marked file as processed: processed/test-file.json.done
[sender][20260428-173155-ac828e63] File marked as processed and moved to processed folder: test-file.json
[sender][20260428-173155-ac828e63] Sender workflow complete
[sender][20260428-173155-ac828e63] pipeline_complete: success
[sender][20260428-173155-ac828e63] Agent workflow completed, sleeping 300s until next run
```

Receiver checks:

- Agent can read landing transfer artifacts.
- Valid transfers are decompressed and written to target bucket.
- Idempotency marker behavior prevents duplicate processing on retries.

Example receiver logs to look for:

```text
[masked-host].ec2.internal
[receiver][20260428-173655-4f72c49a] Executing agent workflow
[receiver][20260428-173655-4f72c49a] pipeline_start: success
[receiver][20260428-173155-ac828e63] Processing transfer from agency_name
[receiver][20260428-173155-ac828e63] extract_data: success
[receiver][20260428-173155-ac828e63] validate_manifest: success
[receiver][20260428-173155-ac828e63] decompress: success
[receiver][20260428-173155-ac828e63] Created marker object processed/agency_name/20260428-173155-ac828e63.done for idempotency
[receiver][20260428-173155-ac828e63] store_data: success
[receiver][20260428-173155-ac828e63] Successfully stored 1 files (328 bytes)
[receiver][20260428-173655-4f72c49a] Receiver scan complete: 1 processed, 6 already processed, 0 failed (last_3_already_processed=['agency_name/20260428-150711-abe09c60', 'agency_name/20260424-164839-b73b2baf', 'agency_name/20260424-153833-5a3b2467'])
[receiver][20260428-173655-4f72c49a] pipeline_complete: success
[receiver][20260428-173655-4f72c49a] Agent workflow completed, sleeping 300s until next run
```

## 11. Common Deployment Errors

- `AGENCY is required and cannot be blank`
  - Set non-empty `AGENCY`.
- `AGENT_MODE must be one of ['receiver', 'sender']`
  - Set valid `AGENT_MODE`.
- `SFTP_ENDPOINTS is required and cannot be blank`
  - Provide sender endpoints when running sender mode.
- S3 access/permission errors
  - Verify workload identity has list/read/write/head access to required buckets/prefixes.

## 12. Operational Notes for Agencies

- Run sender and receiver as separate deployments (ECS tasks, EKS pods, etc).
- Keep `replicas: 1` per mode unless you add explicit distributed locking/idempotency controls for concurrent workers.
- Rotate AWS credentials and secrets using AWS Secrets Manager rotation policies.
- Forward container logs to CloudWatch or your central observability platform for auditing and incident response.
