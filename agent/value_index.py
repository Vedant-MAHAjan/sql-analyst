"""Trigram value index: map literals in a question to values stored in the DB.

Build once per database (needs a writable connection):
  python -m agent.value_index build
Lives in schema "retrieval", which schema linking never shows the model.
"""
import re
import sys

import psycopg
from psycopg import sql

from agent.schema import bird_tables, tables_for

MAX_VALUE_LEN = 80
MAX_VALUES_PER_COLUMN = 5000
TEXT_TYPES = ("text", "character varying", "character")
STOPWORDS = set("""
a an and are as at be by did do does for from had has have how i in is it its
list many much name names number of on or please show that the their there these
they this those to was were what when where which who whom whose why with
""".split())


def build(conn: psycopg.Connection, db_ids: list[str]) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS retrieval")
    conn.execute("DROP TABLE IF EXISTS retrieval.value_index")
    conn.execute("CREATE TABLE retrieval.value_index "
                 "(db_id text, table_name text, column_name text, value text)")
    for db_id in db_ids:
        tables = tables_for(conn, db_id)
        cols = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(%s) "
            "AND data_type = ANY(%s)", (tables, list(TEXT_TYPES))).fetchall()
        for table, col in cols:
            t, c = sql.Identifier(table), sql.Identifier(col)
            conn.execute(sql.SQL(
                "INSERT INTO retrieval.value_index "
                "SELECT %s, %s, %s, v FROM (SELECT DISTINCT rtrim({c}::text) AS v FROM {t} "
                "WHERE {c} IS NOT NULL AND length({c}::text) BETWEEN 1 AND %s "
                "LIMIT %s) s").format(c=c, t=t),
                (db_id, table, col, MAX_VALUE_LEN, MAX_VALUES_PER_COLUMN))
        print(f"{db_id}: {len(cols)} text columns", flush=True)
    conn.execute("CREATE INDEX ON retrieval.value_index USING gin (value gin_trgm_ops)")
    conn.execute("CREATE INDEX ON retrieval.value_index (db_id, lower(value))")
    conn.execute("ANALYZE retrieval.value_index")


def phrases(text: str, max_n: int = 4) -> list[str]:
    """Candidate literals: quoted strings plus word n-grams that are not all stopwords."""
    out = {a or b for a, b in re.findall(r"'([^']{2,80})'|\"([^\"]{2,80})\"", text)}
    words = re.findall(r"[A-Za-z0-9][\w.&/]*", text)
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if all(w.lower() in STOPWORDS for w in gram) or (n == 1 and len(gram[0]) < 3):
                continue
            if gram[0].lower() in STOPWORDS or gram[-1].lower() in STOPWORDS:
                continue
            out.add(" ".join(gram))
    return sorted(out)


def lookup(conn: psycopg.Connection, db_id: str, text: str, threshold: float = 0.65,
           per_phrase: int = 3, limit: int = 15) -> list[tuple[str, str, str, float]]:
    """(table, column, value, similarity) for stored values resembling phrases in text."""
    cands = phrases(text)
    if not cands:
        return []
    conn.execute(f"SET pg_trgm.similarity_threshold = {float(threshold)}")
    # LATERAL keeps one trigram index scan per phrase; a plain join lets the
    # planner compare every phrase with every stored value.
    rows = conn.execute(
        "SELECT h.table_name, h.column_name, h.value, h.sim "
        "FROM unnest(%s::text[]) p CROSS JOIN LATERAL ("
        " SELECT v.table_name, v.column_name, v.value, "
        "  CASE WHEN lower(v.value) = lower(p) THEN 1.0 ELSE similarity(v.value, p) END AS sim "
        " FROM retrieval.value_index v WHERE v.value %% p AND v.db_id = %s "
        " ORDER BY sim DESC, v.value, v.table_name, v.column_name LIMIT %s) h "
        "ORDER BY h.sim DESC, length(h.value) DESC, h.value, h.table_name, h.column_name",
        (cands, db_id, per_phrase)
    ).fetchall()
    seen, out = set(), []
    for table, col, value, sim in rows:
        if (table, col, value) not in seen:
            seen.add((table, col, value))
            out.append((table, col, value, float(sim)))
    return out[:limit]


if __name__ == "__main__" and sys.argv[1:] == ["build"]:
    from eval.db import DSNS, connect
    with connect(DSNS["bird"], timeout_ms=0) as conn:
        build(conn, list(bird_tables()))
    with connect(DSNS["pagila"], timeout_ms=0) as conn:
        build(conn, ["pagila"])
