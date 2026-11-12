"""Confidence intervals and paired tests for comparing runs.

Usage: python -m eval.stats runs/<a> runs/<b>    # paired McNemar, b vs a
"""
import json
import math
import sys
from pathlib import Path


def ci95(correct: int, n: int) -> float:
    """Half-width of the normal-approximation 95% interval, in points."""
    p = correct / n
    return 100 * 1.96 * math.sqrt(p * (1 - p) / n)


def mcnemar(a: dict, b: dict) -> dict:
    """Exact two-sided McNemar on questions both runs answered."""
    qs = [q for q in a if q in b]
    fixed = sum(a[q] == 0 and b[q] == 1 for q in qs)
    broke = sum(a[q] == 1 and b[q] == 0 for q in qs)
    n, k = fixed + broke, min(fixed, broke)
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"n": len(qs), "a_ex": round(100 * sum(a[q] for q in qs) / len(qs), 2),
            "b_ex": round(100 * sum(b[q] for q in qs) / len(qs), 2),
            "fixed": fixed, "broke": broke, "p": round(p, 4)}


def load(run_dir: str | Path, key: str = "correct") -> dict:
    # Keyed by (question_id, occurrence): Mini-Dev repeats questions 137 and 138.
    out, seen = {}, {}
    for r in map(json.loads, open(Path(run_dir, "log.jsonl"))):
        n = seen[r["question_id"]] = seen.get(r["question_id"], 0) + 1
        out[(r["question_id"], n)] = r[key]
    return out


if __name__ == "__main__":
    print(json.dumps(mcnemar(load(sys.argv[1]), load(sys.argv[2]))))
