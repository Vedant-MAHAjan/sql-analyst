"""Phase 0: execute every gold query and record what it returns.

Each PostgreSQL gold query is also checked against the original SQLite gold
query on the SQLite copy of the same database: the PostgreSQL gold SQL was
machine-transpiled, so a result mismatch flags a likely transpilation error.

Usage: python -m eval.gold_audit
"""
import csv
import datetime as dt
import decimal
import json
import sqlite3
import time
from pathlib import Path

import psycopg

from eval.db import connect, result_hash

ROOT = Path(__file__).resolve().parent.parent
MINIDEV = ROOT / "data/raw/minidev/minidev/MINIDEV"
OUT = ROOT / "reports/gold_audit.csv"
SQLITE_TIMEOUT_S = 30
FIELDS = [
    "question_id", "db_id", "difficulty", "status", "row_count",
    "result_hash", "runtime_ms", "error",
    "sqlite_status", "sqlite_row_count", "sqlite_match",
]


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def run_pg(conn: psycopg.Connection, sql: str) -> tuple[dict, list]:
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall() if cur.description else []
    except psycopg.errors.QueryCanceled:
        return {"status": "timeout", "runtime_ms": _ms(start)}, []
    except psycopg.Error as exc:
        msg = (exc.diag.message_primary or str(exc)).splitlines()[0]
        return {"status": "error", "runtime_ms": _ms(start), "error": msg}, []
    return {
        "status": "ok" if rows else "empty",
        "row_count": len(rows),
        "result_hash": result_hash(rows),
        "runtime_ms": _ms(start),
    }, rows


def run_sqlite(db_id: str, sql: str) -> tuple[str, list]:
    path = MINIDEV / "dev_databases" / db_id / f"{db_id}.sqlite"
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    deadline = time.monotonic() + SQLITE_TIMEOUT_S
    conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError as exc:
        return ("timeout" if "interrupted" in str(exc) else "error"), []
    except sqlite3.Error:
        return "error", []
    finally:
        conn.close()
    return ("ok" if rows else "empty"), rows


def _norm_value(v):
    # Dialects differ in numeric types (float4 vs double, Decimal) and
    # in date representation; compare on a common, rounded form.
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, decimal.Decimal)):
        f = float(v)
        if f.is_integer() and abs(f) < 1e15:
            return int(f)
        return float(f"{f:.5g}")
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat(sep=" ") if isinstance(v, dt.datetime) else v.isoformat()
    if isinstance(v, str):
        try:
            return _norm_value(float(v)) if v.strip() else v
        except ValueError:
            return v
    return v


def norm_set(rows: list) -> frozenset:
    return frozenset(tuple(_norm_value(v) for v in r) for r in rows)


def main() -> None:
    pg_items = json.loads((MINIDEV / "mini_dev_postgresql.json").read_text())
    lite = {
        x["question_id"]: x
        for x in json.loads((MINIDEV / "mini_dev_sqlite.json").read_text())
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with connect() as conn, open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for item in pg_items:
            res, pg_rows = run_pg(conn, item["SQL"])
            lite_status, lite_rows = run_sqlite(
                item["db_id"], lite[item["question_id"]]["SQL"]
            )
            match = ""
            if res["status"] in ("ok", "empty") and lite_status in ("ok", "empty"):
                match = int(norm_set(pg_rows) == norm_set(lite_rows))
            row = {
                "question_id": item["question_id"],
                "db_id": item["db_id"],
                "difficulty": item["difficulty"],
                **res,
                "sqlite_status": lite_status,
                "sqlite_row_count": len(lite_rows),
                "sqlite_match": match,
            }
            writer.writerow(row)
            for key in (f"pg_{row['status']}", f"sqlite_match={match}"):
                counts[key] = counts.get(key, 0) + 1
    print(f"{len(pg_items)} gold queries -> {OUT}")
    for key, n in sorted(counts.items()):
        print(f"  {key:16s} {n}")


if __name__ == "__main__":
    main()
