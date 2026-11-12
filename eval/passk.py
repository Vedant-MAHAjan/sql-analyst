"""pass^k reliability: share of questions solved in all k runs (Sierra's tau-bench metric).

Usage: python -m eval.passk runs/<seed1> runs/<seed2> ... [--out report.json]
"""
import argparse
import json
from pathlib import Path

from eval.stats import load


def passk(run_dirs: list[str]) -> dict:
    runs = [load(d) for d in run_dirs]
    qs = sorted(set.intersection(*(set(r) for r in runs)))
    k, n = len(runs), len(qs)
    solved = [sum(r[q] for r in runs) for q in qs]
    return {
        "k": k, "n": n,
        "pass_at_1_mean": round(100 * sum(solved) / (k * n), 2),
        f"pass^{k}": round(100 * sum(s == k for s in solved) / n, 2),
        f"pass@{k}": round(100 * sum(s > 0 for s in solved) / n, 2),
        "per_run_ex": [round(100 * sum(r[q] for q in qs) / n, 2) for r in runs],
        "solved_count_histogram": {str(i): sum(s == i for s in solved) for i in range(k + 1)},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out")
    args = ap.parse_args()
    out = passk(args.runs)
    print(json.dumps(out, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
