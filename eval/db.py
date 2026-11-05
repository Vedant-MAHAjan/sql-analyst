import hashlib
import os

import psycopg

DSN = os.environ.get(
    "BIRD_DSN", "postgresql://postgres:postgres@127.0.0.1:5433/bird"
)
DSNS = {
    "bird": DSN,
    "pagila": os.environ.get("PAGILA_DSN", DSN.rsplit("/", 1)[0] + "/pagila"),
}
# Model-written SQL runs as the read-only analyst role.
_ANALYST = os.environ.get(
    "ANALYST_DSN_BASE", "postgresql://analyst_ro:analyst_ro@127.0.0.1:5433")
ANALYST_DSNS = {"bird": f"{_ANALYST}/bird", "pagila": f"{_ANALYST}/pagila"}


def connect(
    dsn: str = DSN, timeout_ms: int = 30_000, read_only: bool = False
) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
    if read_only:
        conn.execute("SET default_transaction_read_only = on")
    return conn


def result_set(rows: list[tuple]) -> frozenset:
    # BIRD's EX compares set(pred) == set(gold): order and duplicates ignored.
    return frozenset(rows)


def result_hash(rows: list[tuple]) -> str:
    canon = sorted(repr(r) for r in result_set(rows))
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]
