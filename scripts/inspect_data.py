"""Inspect PostgreSQL schemas/tables and preview rows from any table.

This script is useful when psql is unavailable in a container.

Examples
--------
    python inspect_data.py
    python inspect_data.py --schema dot --table contract_data --limit 20
    python inspect_data.py --table dot.contract_data --limit 20
    python inspect_data.py --sslmode require --gssencmode disable
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import psycopg2
    from psycopg2 import sql
    import psycopg2.extras
except ImportError:
    sys.exit("psycopg2 is required. Install with: pip install psycopg2-binary")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect PostgreSQL schemas/tables and preview table data."
    )
    parser.add_argument("--host", default=None, help="Postgres host (default: RDSHOST or localhost)")
    parser.add_argument("--port", type=int, default=None, help="Postgres port (default: RDSPORT or 5432)")
    parser.add_argument("--dbname", default=None, help="Database name (default: RDSDB or postgres)")
    parser.add_argument("--user", default=None, help="Username (default: RDSUSER or postgres)")
    parser.add_argument("--password", default=None, help="Password (default: RDSPASSWORD or empty)")
    parser.add_argument(
        "--schema",
        default=None,
        help="Schema to inspect (default: RDSSCHEMA or dot)",
    )
    parser.add_argument(
        "--table",
        default="contract_data",
        help="Table to preview (default: contract_data); supports schema.table",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of rows to preview from table (default: 10)",
    )
    parser.add_argument(
        "--sslmode",
        default=None,
        help="Postgres SSL mode (default: PGSSLMODE)",
    )
    parser.add_argument(
        "--gssencmode",
        default=None,
        help="Postgres GSS encryption mode (default: PGGSSENCMODE)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=None,
        help="Connection timeout in seconds (default: PGCONNECT_TIMEOUT or 10)",
    )
    return parser.parse_args()


def resolve_target(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve target schema and table from args/env, including schema.table syntax."""
    default_schema = args.schema or os.getenv("RDSSCHEMA", "dot")
    if "." in args.table:
        table_schema, table_name = args.table.split(".", 1)
        return table_schema, table_name
    return default_schema, args.table


def resolve_connection(args: argparse.Namespace) -> tuple[str, int, str, str, str, str, str, int]:
    host = args.host or os.getenv("RDSHOST", "localhost")
    port = args.port or int(os.getenv("RDSPORT", "5432"))
    dbname = args.dbname or os.getenv("RDSDB", "postgres")
    user = args.user or os.getenv("RDSUSER", "postgres")
    password = args.password or os.getenv("RDSPASSWORD", "")
    sslmode = args.sslmode or os.getenv("PGSSLMODE", "")
    gssencmode = args.gssencmode or os.getenv("PGGSSENCMODE", "")
    connect_timeout = args.connect_timeout or int(os.getenv("PGCONNECT_TIMEOUT", "10"))
    return host, port, dbname, user, password, sslmode, gssencmode, connect_timeout


def build_dsn(args: argparse.Namespace) -> str:
    host, port, dbname, user, password, sslmode, gssencmode, connect_timeout = resolve_connection(args)
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


def main() -> None:
    args = parse_args()
    schema, table = resolve_target(args)
    dsn = build_dsn(args)
    host, port, dbname, user, _, sslmode, gssencmode, connect_timeout = resolve_connection(args)

    print("Connecting to PostgreSQL ...")
    print(
        "Connection target: "
        f"host={host} port={port} dbname={dbname} user={user} "
        f"sslmode={sslmode or 'default'} gssencmode={gssencmode or 'default'} "
        f"connect_timeout={connect_timeout}"
    )

    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        sys.exit(f"Could not connect to PostgreSQL: {exc}")

    print("Connected successfully.\n")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                ORDER BY schema_name
                """
            )
            schemas = [row["schema_name"] for row in cur.fetchall()]
            print("Schemas:")
            for name in schemas:
                print(f"  - {name}")

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (schema,),
            )
            tables = [row["table_name"] for row in cur.fetchall()]
            print(f"\nTables in schema '{schema}':")
            if tables:
                for name in tables:
                    print(f"  - {name}")
            else:
                print("  (none)")

            count_query = sql.SQL("SELECT COUNT(*) AS row_count FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            )
            cur.execute(count_query)
            total = cur.fetchone()["row_count"]

            data_query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
                sql.Identifier(schema),
                sql.Identifier(table),
            )
            cur.execute(data_query, (args.limit,))
            rows = cur.fetchall()

            print(f"\nData summary for {schema}.{table}:")
            print(f"  Total rows: {total}")
            print(f"  Showing up to {args.limit} row(s):")
            print(json.dumps(rows, default=str, indent=2))

    except psycopg2.errors.UndefinedTable:
        print(f"\nTable '{schema}.{table}' does not exist.")
    except psycopg2.Error as exc:
        sys.exit(f"PostgreSQL error: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()