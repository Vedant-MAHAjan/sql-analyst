"""Serving-path execution: a server-side cursor capped at fetch time.

The query text is never rewritten (an injected LIMIT would change results);
PostgreSQL produces rows only as they are fetched, so a big result costs
max_rows + 1 rows, not all of them.
"""
import itertools
import time

import psycopg

from eval.evaluator import Exec, _snake

_ids = itertools.count()


def _size(row: tuple) -> int:
    return sum(len(v) if isinstance(v, (str, bytes)) else 16 for v in row)


def execute_capped(conn: psycopg.Connection, sql: str, max_rows: int = 1000,
                   max_bytes: int = 20_000_000) -> Exec:
    start = time.perf_counter()
    rows: list = []
    size, over_bytes = 0, False
    try:
        with conn.transaction(), conn.cursor(name=f"q{next(_ids)}") as cur:
            cur.execute(sql)
            # Small batches so a few huge values cannot flood memory before the check.
            while len(rows) <= max_rows and (batch := cur.fetchmany(20)):
                for row in batch:
                    rows.append(row)
                    size += _size(row)
                    if size > max_bytes:
                        over_bytes = True
                        break
                if over_bytes:
                    break
            columns = [d.name for d in cur.description or []]
    except psycopg.errors.QueryCanceled:
        return Exec("timeout", error_type="timeout", ms=_ms(start))
    except psycopg.Error as exc:
        diag = exc.diag
        msg = (getattr(diag, "message_primary", None) or str(exc)).splitlines()
        return Exec("error", error_type=_snake(type(exc).__name__),
                    error=msg[0] if msg else "", ms=_ms(start),
                    hint=getattr(diag, "message_hint", None) or "",
                    position=int(getattr(diag, "statement_position", None) or 0))
    return Exec("ok", rows[:max_rows], ms=_ms(start), columns=columns,
                truncated=len(rows) > max_rows or over_bytes)


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _reset(conn: psycopg.Connection) -> None:
    # Model SQL may open its own transaction (BEGIN ...); never leave it aborted.
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        conn.execute("ROLLBACK")


def execute_any(conn: psycopg.Connection, sql: str, max_rows: int = 1000,
                max_bytes: int = 20_000_000) -> Exec:
    """Like execute_capped, but statements a cursor cannot hold (INSERT, DELETE,
    DDL, data-modifying WITH) are run directly, so only the database role stops
    them. Used by the attack suite to measure the role on its own."""
    ex = execute_capped(conn, sql, max_rows, max_bytes)
    if ex.status != "error" or ex.error_type not in ("syntax_error", "feature_not_supported"):
        return ex
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(max_rows + 1) if cur.description else []
            columns = [d.name for d in cur.description or []]
    except psycopg.Error as exc:
        _reset(conn)
        diag = exc.diag
        msg = (getattr(diag, "message_primary", None) or str(exc)).splitlines()
        etype = "timeout" if isinstance(exc, psycopg.errors.QueryCanceled) else _snake(type(exc).__name__)
        return Exec("timeout" if etype == "timeout" else "error", error_type=etype,
                    error=msg[0] if msg else "", ms=_ms(start),
                    hint=getattr(diag, "message_hint", None) or "",
                    position=int(getattr(diag, "statement_position", None) or 0))
    _reset(conn)
    return Exec("ok", rows[:max_rows], ms=_ms(start), columns=columns,
                truncated=len(rows) > max_rows)
