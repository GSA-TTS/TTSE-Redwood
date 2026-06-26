# Pod Postgres Quickstart

This quick guide captures the validated flow for testing scripts and PostgreSQL access from a Rancher pod.

## 1) Open Rancher and start Exec Shell

1. Log in to Rancher (use your GitHub credentials):
   - https://rancher.staging.core.mcaas.fcs.gsa.gov/dashboard/c/c-th97g/explorer#cluster-events
2. Go to `Workloads`.
3. Under `Deployments`, select the cluster/deployment where you want to run code.
4. In the top-right menu (`...`), click `Exec Shell`.
5. Shell opens at `/app$`.

## 2) Move to writable area in pod

```bash
cd ..
cd tmp
```

You can create files/folders in `/tmp` and edit with `vi`.

## 3) Verify required tools in pod image

The pod should include:
- `vim-tiny`
- `postgresql-client` (for `psql`)

If missing, update image build and redeploy:

```dockerfile
RUN apt-get update && apt-get upgrade -y && \
	apt-get install -y --no-install-recommends vim-tiny postgresql-client && \
	apt-get clean && rm -rf /var/lib/apt/lists/*
```

## 4) Set database environment variables in shell

```bash
export RDSHOST="tts-core-dev-everglades.con0e6om039j.us-east-1.rds.amazonaws.com"
export RDSPORT=5432
export RDSUSER="everglades_admin"
export RDSDB="tts_core_dev_everglades"
export RDSPASSWORD="<password>"
# Optional: defaults to dot when unset
export RDSSCHEMA="dot"
```

## 5) Create files in /tmp and run from shell

Create your working files in `/tmp` (for example with `vi`), then run them directly from there.

Example:

```bash
cd /tmp
mkdir -p sql
vi generate_synthetic_data.py
vi sql/contract_data.sql
python generate_synthetic_data.py --table contract_data --records 100
```

Notes:
- Default schema is `dot` when `--schema` and `RDSSCHEMA` are not provided.
- Keep Python script outside `sql/` (for example: `/tmp/generate_synthetic_data.py`).
- Keep DDL files inside `sql/` (for example: `/tmp/sql/contract_data.sql`).
- DDL auto-discovery uses `<script_directory>/sql/<table>.sql` when present.

## 6) Connect with psql and validate data

```bash
PGPASSWORD="$RDSPASSWORD" psql -h "$RDSHOST" -p "${RDSPORT:-5432}" -U "$RDSUSER" -d "$RDSDB"
```

Inside `psql`, run one line at a time:

```sql
\conninfo
\dn
\dt dot.*
SELECT COUNT(*) FROM dot.contract_data;
SELECT * FROM dot.contract_data ORDER BY award_date DESC LIMIT 10;
```

To disconnect from `psql`, run this on a separate line:

```sql
\q
```

## 7) Session timeout warning

Exec Shell sessions are short-lived and can disconnect quickly when idle.
If disconnected, open a new Exec Shell and repeat the steps.

## Troubleshooting

### Error: local socket not found

```text
connection to server on socket "/var/run/postgresql/.s.PGSQL.5432" failed
```

Cause:
- `psql` was run without host/user/db settings.

Fix:
- Use the full `PGPASSWORD=... psql -h ... -U ... -d ...` command from Step 6.

### If psql command parsing looks wrong

- Press `Ctrl+C` once to clear input.
- Re-run commands one per line.
