"""Execution-based scoring, matching BIRD's evaluation_ex.py / evaluation_f1.py.

- ex:      set(pred_rows) == set(gold_rows)   (official EX)
- ex_tol:  same, after normalising numbers to 4 significant digits, dates to
           ISO text and trimming char(n) padding (secondary; float4 golds)
- soft_f1: BIRD's Soft-F1, reimplemented to give identical values
"""
import datetime as dt
import decimal
import re
import time
from dataclasses import dataclass, field

import psycopg

MAX_ROWS = 200_000


@dataclass
class Exec:
    status: str  # ok | error | timeout | too_many_rows
    rows: list = field(default_factory=list)
    error_type: str = ""
    error: str = ""
    ms: int = 0
    hint: str = ""
    position: int = 0
    columns: list = field(default_factory=list)
    truncated: bool = False


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def execute(conn: psycopg.Connection, sql: str) -> Exec:
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows: list = []
            if cur.description:
                while batch := cur.fetchmany(10_000):
                    rows.extend(batch)
                    if len(rows) > MAX_ROWS:
                        return Exec("too_many_rows", error_type="too_many_rows",
                                    ms=_ms(start))
    except psycopg.errors.QueryCanceled:
        return Exec("timeout", error_type="timeout", ms=_ms(start))
    except psycopg.Error as exc:
        diag = exc.diag
        msg = (getattr(diag, "message_primary", None) or str(exc)).splitlines()
        return Exec("error", error_type=_snake(type(exc).__name__),
                    error=msg[0] if msg else "", ms=_ms(start),
                    hint=getattr(diag, "message_hint", None) or "",
                    position=int(getattr(diag, "statement_position", None) or 0))
    return Exec("ok", rows, ms=_ms(start))


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def ex(pred: list, gold: list) -> int:
    return int(set(pred) == set(gold))


def _norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, decimal.Decimal)):
        f = float(v)
        if f.is_integer() and abs(f) < 1e15:
            return int(f)
        return float(f"{f:.4g}")
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, str):
        return v.rstrip()
    if isinstance(v, list):  # PostgreSQL arrays
        return tuple(_norm(x) for x in v)
    return v


def ex_tol(pred: list, gold: list) -> int:
    norm = lambda rows: {tuple(_norm(v) for v in r) for r in rows}  # noqa: E731
    return int(norm(pred) == norm(gold))


def soft_f1(pred: list, gold: list) -> float:
    if not pred and not gold:
        return 1.0
    pred = list(dict.fromkeys(pred))
    gold = list(dict.fromkeys(gold))
    tp = fp = fn = 0.0
    for i, g in enumerate(gold):
        if i >= len(pred):
            fn += 1
            continue
        p, width = pred[i], len(g)
        tp += sum(v in g for v in p) / width
        fp += sum(v not in g for v in p) / width
        fn += sum(v not in p for v in g) / width
    fp += max(len(pred) - len(gold), 0)
    precision = tp / (tp + fp) if tp + fp > 0 else 0
    recall = tp / (tp + fn) if tp + fn > 0 else 0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score(pred: Exec, gold_rows: list) -> dict:
    if pred.status != "ok":
        return {"ex": 0, "ex_tol": 0, "soft_f1": 0.0}
    try:
        official = {"ex": ex(pred.rows, gold_rows), "soft_f1": soft_f1(pred.rows, gold_rows)}
    except TypeError:
        # Array values are unhashable; BIRD's scripts raise here and score 0.
        official = {"ex": 0, "soft_f1": 0.0}
    return {**official, "ex_tol": ex_tol(pred.rows, gold_rows)}
