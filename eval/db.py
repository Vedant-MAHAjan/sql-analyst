import hashlib
import os

import psycopg

DSN = os.environ.get(
    "BIRD_DSN", "postgresql://postgres:postgres@127.0.0.1:5433/bird"
)


def connect(dsn: str = DSN, timeout_ms: int = 30_000) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
    return conn


def result_set(rows: list[tuple]) -> frozenset:
    # BIRD's EX compares set(pred) == set(gold): order and duplicates ignored.
    return frozenset(rows)


def result_hash(rows: list[tuple]) -> str:
    canon = sorted(repr(r) for r in result_set(rows))
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]
