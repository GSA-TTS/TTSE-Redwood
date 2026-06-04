"""Generate synthetic rows for a PostgreSQL table.

Usage:
    python generate_synthetic_data.py --table contract_data --records 100

Connection values come from CLI flags first, then environment variables:
`RDSHOST`, `RDSPORT`, `RDSUSER`, `RDSDB`, `RDSPASSWORD`, `RDSSCHEMA`.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta

try:
    from psycopg2 import sql
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit(
        "psycopg2 is required.  Install with:  pip install psycopg2-binary"
    )

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

_CONTRACT_TYPES = ["FFP", "CPFF", "T&M", "CPAF", "IDIQ"]

_AGENCY_PREFIXES = [
    "GS", "FA", "N0", "W9", "HSHQ", "W5", "SPRPA", "DE", "GS2",
]

_VENDOR_WORDS = [
    "Acme", "TechCorp", "Digital", "Federal", "Cloud", "DataSystems",
    "CyberSecurity", "Network", "Enterprise", "Consulting", "Infrastructure",
    "Application", "Integrated", "Advanced", "National", "Pacific", "Apex",
    "Nexus", "Pinnacle", "Summit", "Vanguard", "Sentinel", "Cobalt",
    "Atlas", "Zenith", "Meridian", "Horizon", "Orion", "Vector",
]

_VENDOR_SUFFIXES = [
    "Solutions", "Technologies", "Industries", "Services", "Group",
    "Partners", "LLC", "Inc", "Corp", "Associates", "Experts", "Systems",
    "Specialists", "Developers", "Consultants",
]


def _random_piid() -> str:
    prefix = random.choice(_AGENCY_PREFIXES)
    year = random.randint(21, 26)
    seq = random.randint(1, 9999)
    suffix = random.choice(["C", "D"])
    return f"{prefix}{year:02d}{suffix}-{year:02d}-{suffix}-{seq:04d}"


def _random_vendor_name() -> str:
    parts = random.sample(_VENDOR_WORDS, k=random.randint(1, 2))
    suffix = random.choice(_VENDOR_SUFFIXES)
    return " ".join(parts + [suffix])


def _random_duns() -> str:
    return str(random.randint(100_000_000, 999_999_999))


def _random_contract_value() -> float:
    return round(random.uniform(50_000, 10_000_000), 2)


def _random_dates() -> tuple[date, date, date]:
    award_date = date(
        random.randint(2021, 2026),
        random.randint(1, 12),
        random.randint(1, 28),
    )
    start_date = award_date + timedelta(days=random.randint(15, 45))
    end_date = start_date + timedelta(days=random.randint(365, 365 * 3))
    return award_date, start_date, end_date


def generate_value_for_column(
    column_name: str,
    data_type: str,
    udt_name: str,
    row_index: int,
    enum_values: dict[str, list[str]],
) -> object:
    """Generate a generic synthetic value based on column metadata."""
    name = column_name.lower()
    dtype = data_type.lower()

    if dtype == "uuid":
        return str(uuid.uuid4())

    if dtype in ("smallint", "integer", "bigint"):
        return random.randint(1, 1_000_000)

    if dtype in ("numeric", "decimal", "real", "double precision"):
        return round(random.uniform(1, 1_000_000), 2)

    if dtype == "boolean":
        return random.choice([True, False])

    if dtype == "date":
        base = date(2021, 1, 1)
        return base + timedelta(days=random.randint(0, 365 * 6))

    if "timestamp" in dtype:
        return datetime.utcnow() - timedelta(days=random.randint(0, 365 * 3))

    if dtype in ("character", "character varying", "text", "citext"):
        if "piid" in name:
            return _random_piid()
        if "duns" in name:
            return _random_duns()
        if "name" in name:
            return _random_vendor_name()
        if "type" in name:
            return random.choice(_CONTRACT_TYPES)
        if "email" in name:
            return f"user{row_index}@example.com"
        return f"{column_name}_{row_index}"

    if dtype == "user-defined" and udt_name in enum_values and enum_values[udt_name]:
        return random.choice(enum_values[udt_name])

    return f"{column_name}_{row_index}"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

BATCH_SIZE = 500


def build_dsn(args: argparse.Namespace) -> str:
    """Resolve DSN from RDS env vars and CLI flags.

    Resolution order (first value found wins):
        1. CLI flag
        2. RDS* environment variable (RDSHOST, RDSPORT, RDSUSER, RDSDB, RDSPASSWORD)
        3. Hard-coded default

    Expected environment variables:
        export RDSHOST="tts-core-dev-everglades.con0e6om039j.us-east-1.rds.amazonaws.com"
        export RDSPORT=5432
        export RDSUSER="everglades_admin"
        export RDSDB="tts_core_dev_everglades"
        export RDSPASSWORD="test"
        export RDSSCHEMA="dot"      # optional, defaults to dot
    """
    host = args.host or os.getenv("RDSHOST", "localhost")
    port = args.port or int(os.getenv("RDSPORT", "5432"))
    dbname = args.dbname or os.getenv("RDSDB", "postgres")
    user = args.user or os.getenv("RDSUSER", "postgres")
    password = args.password or os.getenv("RDSPASSWORD", "")
    sslmode = args.sslmode or os.getenv("PGSSLMODE", "")
    gssencmode = args.gssencmode or os.getenv("PGGSSENCMODE", "")
    connect_timeout = args.connect_timeout or int(os.getenv("PGCONNECT_TIMEOUT", "10"))

    dsn_parts = [
        f"host={host}",
        f"port={port}",
        f"dbname={dbname}",
        f"user={user}",
        f"password={password}",
        f"connect_timeout={connect_timeout}",
    ]
    if sslmode:
        dsn_parts.append(f"sslmode={sslmode}")
    if gssencmode:
        dsn_parts.append(f"gssencmode={gssencmode}")

    return " ".join(dsn_parts)


def resolved_connection_target(args: argparse.Namespace) -> tuple[str, int, str, str, str, str, int]:
    """Return resolved connection details for safe debug logging."""
    host = args.host or os.getenv("RDSHOST", "localhost")
    port = args.port or int(os.getenv("RDSPORT", "5432"))
    dbname = args.dbname or os.getenv("RDSDB", "postgres")
    user = args.user or os.getenv("RDSUSER", "postgres")
    sslmode = args.sslmode or os.getenv("PGSSLMODE", "")
    gssencmode = args.gssencmode or os.getenv("PGGSSENCMODE", "")
    connect_timeout = args.connect_timeout or int(os.getenv("PGCONNECT_TIMEOUT", "10"))
    return host, port, dbname, user, sslmode, gssencmode, connect_timeout


def resolve_qualified_table(schema: str, table: str) -> str:
    """Return schema-qualified table name, e.g. calm.contract_data."""
    # If the caller already qualified the name (contains a dot) use it as-is.
    if "." in table:
        return table
    return f"{schema}.{table}"


def split_table_name(qualified_table: str, default_schema: str) -> tuple[str, str]:
    """Split schema-qualified name into schema and table parts."""
    if "." in qualified_table:
        schema_name, table_name = qualified_table.split(".", 1)
        return schema_name, table_name
    return default_schema, qualified_table


def default_ddl_file_for_table(table_name: str) -> str:
    """Return default DDL file path under scripts/sql for a table."""
    return os.path.join(os.path.dirname(__file__), "sql", f"{table_name}.sql")


def create_schema_if_needed(cursor, schema: str) -> None:
    """Create schema if it does not already exist."""
    cursor.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {};").format(sql.Identifier(schema))
    )


def apply_ddl_file(
    cursor,
    ddl_file: str,
    schema: str,
    qualified_table: str,
) -> None:
    """Apply DDL from a SQL file.

    The SQL file can optionally use either {schema}/{table} placeholders or
    {{schema}}/{{table}} placeholders.
    """
    if not os.path.exists(ddl_file):
        raise FileNotFoundError(f"DDL file not found: {ddl_file}")

    with open(ddl_file, "r", encoding="utf-8") as handle:
        ddl_sql = handle.read()

    ddl_sql = ddl_sql.replace("{{schema}}", schema).replace("{{table}}", qualified_table)
    ddl_sql = ddl_sql.replace("{schema}", schema).replace("{table}", qualified_table)
    cursor.execute(ddl_sql)


def discover_table_columns(cursor, schema: str, table: str) -> list[dict[str, str | None]]:
    """Read ordered table columns with metadata from information_schema."""
    cursor.execute(
        """
        SELECT column_name, data_type, udt_name, is_nullable, identity_generation
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (schema, table),
    )
    return [
        {
            "column_name": row[0],
            "data_type": row[1],
            "udt_name": row[2],
            "is_nullable": row[3],
            "identity_generation": row[4],
        }
        for row in cursor.fetchall()
    ]


def discover_primary_key_columns(cursor, schema: str, table: str) -> list[str]:
    """Discover primary-key columns for conflict handling."""
    cursor.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
          AND tc.table_name = %s
        ORDER BY kcu.ordinal_position;
        """,
        (schema, table),
    )
    return [row[0] for row in cursor.fetchall()]


def discover_enum_values(cursor, schema: str, udt_name: str) -> list[str]:
    """Return enum labels for a user-defined enum type."""
    cursor.execute(
        """
        SELECT e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON t.oid = e.enumtypid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = %s AND t.typname = %s
        ORDER BY e.enumsortorder;
        """,
        (schema, udt_name),
    )
    return [row[0] for row in cursor.fetchall()]


def build_dynamic_insert_sql(
    schema: str,
    table: str,
    columns: list[str],
    conflict_columns: list[str],
) -> sql.Composed:
    """Build INSERT SQL from discovered columns."""
    column_identifiers = [sql.Identifier(col) for col in columns]
    placeholders = [sql.Placeholder() for _ in columns]

    query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(column_identifiers),
        sql.SQL(", ").join(placeholders),
    )

    if conflict_columns:
        query += sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(
            sql.SQL(", ").join([sql.Identifier(col) for col in conflict_columns])
        )

    query += sql.SQL(";")
    return query


def generate_rows_for_columns(
    columns: list[dict[str, str | None]],
    n: int,
    enum_values: dict[str, list[str]],
) -> list[tuple[object, ...]]:
    """Generate synthetic rows aligned to discovered column metadata."""
    insertable_columns = [c for c in columns if c["identity_generation"] is None]
    if not insertable_columns:
        raise RuntimeError("No insertable columns found in target table.")

    rows: list[tuple[object, ...]] = []
    for row_index in range(n):
        row = []
        for col in insertable_columns:
            row.append(
                generate_value_for_column(
                    col["column_name"] or "",
                    col["data_type"] or "",
                    col["udt_name"] or "",
                    row_index,
                    enum_values,
                )
            )
        rows.append(tuple(row))
    return rows


def insert_batches_dynamic(cursor, insert_sql: str, rows: list[tuple[object, ...]]) -> None:
    """Insert rows in batches using pre-built SQL."""
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        psycopg2.extras.execute_batch(cursor, insert_sql, batch, page_size=BATCH_SIZE)
        print(f"  Inserted rows {i + 1}–{i + len(batch)}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic table data and insert into PostgreSQL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--records", "-n",
        type=int,
        default=100,
        help="Number of synthetic rows to generate (default: 100)",
    )
    p.add_argument(
        "--schema",
        default=None,
        help="Postgres schema name (default: RDSSCHEMA or dot)",
    )
    p.add_argument(
        "--table",
        default="contract_data",
        help="Table name without schema (default: contract_data); supports schema.table",
    )
    p.add_argument("--host", default=None, help="Postgres host (default: RDSHOST or localhost)")
    p.add_argument("--port", type=int, default=None, help="Postgres port (default: RDSPORT or 5432)")
    p.add_argument("--dbname", default=None, help="Database name (default: RDSDB or postgres)")
    p.add_argument("--user", default=None, help="Username (default: RDSUSER or postgres)")
    p.add_argument("--password", default=None, help="Password (default: RDSPASSWORD or empty)")
    p.add_argument(
        "--sslmode",
        default=None,
        help="Postgres SSL mode (default: PGSSLMODE, e.g. require)",
    )
    p.add_argument(
        "--gssencmode",
        default=None,
        help="Postgres GSS encryption mode (default: PGGSSENCMODE, e.g. disable)",
    )
    p.add_argument(
        "--connect-timeout",
        type=int,
        default=None,
        help="Postgres connection timeout in seconds (default: PGCONNECT_TIMEOUT or 10)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible data (optional)",
    )
    p.add_argument(
        "--drop",
        action="store_true",
        help="Drop the table before re-creating it (use with caution)",
    )
    p.add_argument(
        "--connect-only",
        action="store_true",
        help="Only test PostgreSQL connection and exit",
    )
    p.add_argument(
        "--ddl-file",
        default=None,
        help=(
            "Path to external SQL file used to create/alter table before inserts "
            "(defaults to <script_dir>/sql/<table>.sql when present)"
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")

    schema = args.schema or os.getenv("RDSSCHEMA", "dot")
    qualified_table = resolve_qualified_table(schema, args.table)

    dsn = build_dsn(args)
    host, port, dbname, user, sslmode, gssencmode, connect_timeout = resolved_connection_target(args)
    print(f"Connecting to PostgreSQL …")
    print(f"Connection target: host={host} port={port} dbname={dbname} user={user}")
    print(f"Connection options: sslmode={sslmode or 'default'} gssencmode={gssencmode or 'default'} connect_timeout={connect_timeout}")
    print(f"Schema: {schema}")
    print(f"Table:  {qualified_table}")

    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        sys.exit(f"Could not connect to PostgreSQL: {exc}")

    print("Connected to PostgreSQL successfully.")

    if args.connect_only:
        conn.close()
        print("Connection test complete. Exiting without loading data.")
        return

    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            table_schema, table_name = split_table_name(qualified_table, schema)

            if args.drop:
                confirm = input(
                    f"WARNING: DROP TABLE {qualified_table}? Type yes to confirm: "
                )
                if confirm.strip().lower() != "yes":
                    print("Aborted.")
                    return
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE;").format(
                        sql.Identifier(table_schema),
                        sql.Identifier(table_name),
                    )
                )
                print(f"Dropped table {qualified_table}.")

            create_schema_if_needed(cur, table_schema)

            ddl_file = args.ddl_file
            if not ddl_file:
                auto_ddl_file = default_ddl_file_for_table(table_name)
                if os.path.exists(auto_ddl_file):
                    ddl_file = auto_ddl_file
                    print(f"Using default DDL file '{ddl_file}' …")

            if ddl_file:
                print(f"Applying DDL file '{ddl_file}' …")
                apply_ddl_file(cur, ddl_file, table_schema, qualified_table)
            else:
                print(
                    "No DDL file provided; assuming table already exists: "
                    f"'{qualified_table}'"
                )

            columns = discover_table_columns(cur, table_schema, table_name)
            if not columns:
                raise RuntimeError(
                    f"No columns discovered for table '{qualified_table}'. "
                    "Verify your DDL and schema/table settings."
                )

            insertable_columns = [c for c in columns if c["identity_generation"] is None]
            insertable_column_names = [c["column_name"] for c in insertable_columns if c["column_name"]]
            if not insertable_column_names:
                raise RuntimeError(
                    f"No insertable columns discovered for table '{qualified_table}'."
                )

            enum_values: dict[str, list[str]] = {}
            for col in columns:
                if (col["data_type"] or "").lower() == "user-defined" and col["udt_name"]:
                    if col["udt_name"] not in enum_values:
                        enum_values[col["udt_name"]] = discover_enum_values(
                            cur,
                            table_schema,
                            col["udt_name"],
                        )

            pk_columns = discover_primary_key_columns(cur, table_schema, table_name)
            if pk_columns:
                print(f"Primary key columns: {', '.join(pk_columns)}")

            print(
                "Discovered insertable columns: "
                f"{', '.join(insertable_column_names)}"
            )

            print(f"Generating {args.records} synthetic record(s) …")
            rows = generate_rows_for_columns(columns, args.records, enum_values)
            insert_sql = build_dynamic_insert_sql(
                table_schema,
                table_name,
                insertable_column_names,
                [col for col in pk_columns if col in insertable_column_names],
            ).as_string(cur)

            print(f"Inserting records into '{qualified_table}' …")
            insert_batches_dynamic(cur, insert_sql, rows)

            conn.commit()

        print(f"\nDone. {args.records} record(s) inserted into '{qualified_table}'.")

    except Exception as exc:
        conn.rollback()
        sys.exit(f"Error during data load: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
