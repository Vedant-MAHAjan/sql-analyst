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


def execute_capped(conn: psycopg.Connection, sql: str, max_rows: int = 1000) -> Exec:
    start = time.perf_counter()
    try:
        with conn.transaction(), conn.cursor(name=f"q{next(_ids)}") as cur:
            cur.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
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
                truncated=len(rows) > max_rows)


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
