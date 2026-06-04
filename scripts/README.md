# Scripts Quick Start

Use these two scripts:
- `generate_synthetic_data.py`: insert test data
- `inspect_data.py`: view table data

## 1) Set DB env vars 

Note: You can find these DB details in AWS (Secrets Manager).

```bash
export RDSHOST="hostname"
export RDSPORT=5432
export RDSUSER="user"
export RDSDB="tts_core_dev_everglades"
export RDSPASSWORD="<password>"
export RDSSCHEMA="dot"   # optional
```

## 2) Generate data

```bash
python scripts/generate_synthetic_data.py --schema dot --table contract_data --records 100
```

Default schema is `dot` for now, so `--schema dot` is optional.

Optional (recreate table first):

```bash
python scripts/generate_synthetic_data.py --schema dot --table contract_data --records 100 --drop
```

## 3) Inspect data

```bash
python scripts/inspect_data.py --schema dot --table contract_data --limit 10
```

## DDL (simple rule)

- If you pass `--ddl-file`, it uses that file.
- If you do not pass `--ddl-file`, it looks for one file only:
  - `<script_dir>/sql/<table>.sql`
- It does not run all SQL files.

## Rancher /tmp usage

See the detailed pod workflow in [scripts/POD_POSTGRES_QUICKSTART.md](scripts/POD_POSTGRES_QUICKSTART.md).
