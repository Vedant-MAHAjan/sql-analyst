"""Render a database's schema as CREATE TABLE statements for the prompt."""
import json
import re
from functools import lru_cache
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DEV_TABLES = ROOT / "data/raw/minidev/minidev/MINIDEV/dev_tables.json"
PLAIN = re.compile(r"^[a-z_][a-z0-9_]*$")
# Model SQL runs as this role; the prompt only shows columns it can read.
EXEC_ROLE = "analyst_ro"
READABLE = ("has_column_privilege(%s, format('%%I.%%I', table_schema, table_name), "
            "column_name, 'SELECT')")


@lru_cache
def bird_tables() -> dict[str, list[str]]:
    # All 11 BIRD databases share one PostgreSQL schema; this maps each db_id
    # to its tables.
    return {
        d["db_id"]: [t.lower() for t in d["table_names_original"]]
        for d in json.loads(DEV_TABLES.read_text())
    }


def _quote_fn(conn: psycopg.Connection):
    reserved = {r[0] for r in conn.execute(
        "SELECT word FROM pg_get_keywords() WHERE catcode IN ('R', 'T')")}

    def q(name: str) -> str:
        if PLAIN.match(name) and name not in reserved:
            return name
        return '"' + name.replace('"', '""') + '"'
    return q


def tables_for(conn: psycopg.Connection, db_id: str) -> list[str]:
    if db_id in bird_tables():
        return bird_tables()[db_id]
    # Other databases: every base table, hiding partitions (Pagila's payment).
    return [r[0] for r in conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
        "ORDER BY 1")]


def ddl(conn: psycopg.Connection, db_id: str) -> str:
    q = _quote_fn(conn)
    tables = tables_for(conn, db_id)
    cols = conn.execute(
        "SELECT table_name, column_name, "
        "CASE WHEN data_type = 'USER-DEFINED' THEN udt_name "
        "WHEN data_type = 'ARRAY' THEN substr(udt_name, 2) || '[]' ELSE data_type END "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = ANY(%s) AND " + READABLE +
        " ORDER BY table_name, ordinal_position", (tables, EXEC_ROLE)
    ).fetchall()
    keys = conn.execute(
        "SELECT rel.relname, con.contype, "
        "(SELECT array_agg(a.attname ORDER BY k.n) FROM unnest(con.conkey) "
        " WITH ORDINALITY k(attnum, n) JOIN pg_attribute a "
        " ON a.attrelid = con.conrelid AND a.attnum = k.attnum), "
        "frel.relname, "
        "(SELECT array_agg(a.attname ORDER BY k.n) FROM unnest(con.confkey) "
        " WITH ORDINALITY k(attnum, n) JOIN pg_attribute a "
        " ON a.attrelid = con.confrelid AND a.attnum = k.attnum) "
        "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
        "LEFT JOIN pg_class frel ON frel.oid = con.confrelid "
        "JOIN pg_namespace n ON n.oid = rel.relnamespace "
        "WHERE n.nspname = 'public' AND con.contype IN ('p', 'f') "
        "AND rel.relname = ANY(%s) ORDER BY con.conname", (tables,)
    ).fetchall()
    by_table: dict[str, list[str]] = {t: [] for t in tables}
    for table, col, typ in cols:
        by_table[table].append(f"  {q(col)} {typ}")
    for table, kind, ccols, ftable, fcols in keys:
        names = ", ".join(q(c) for c in ccols)
        if kind == "p":
            by_table[table].append(f"  PRIMARY KEY ({names})")
        elif ftable in by_table:
            fnames = ", ".join(q(c) for c in fcols)
            by_table[table].append(
                f"  FOREIGN KEY ({names}) REFERENCES {q(ftable)} ({fnames})")
    return "\n\n".join(
        f"CREATE TABLE {q(t)} (\n" + ",\n".join(lines) + "\n);"
        for t, lines in by_table.items() if lines
    )
