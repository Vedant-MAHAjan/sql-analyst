"""Run the held-out gold queries and check them against frozen results.

Usage:
  python -m eval.heldout_check            # verify against expected.json
  python -m eval.heldout_check --freeze   # (re)write expected.json
"""
import collections
import json
import sys
from pathlib import Path

from eval.db import DSN, connect
from eval.gold_audit import run_pg

ROOT = Path(__file__).resolve().parent.parent
HELDOUT = ROOT / "data/heldout"
PAGILA_DSN = DSN.rsplit("/", 1)[0] + "/pagila"


def main(freeze: bool) -> int:
    items = [json.loads(line) for line in open(HELDOUT / "questions.jsonl")]
    exp_path = HELDOUT / "expected.json"
    expected = {} if freeze else json.loads(exp_path.read_text())
    got, failures = {}, []
    with connect(PAGILA_DSN) as conn:
        for item in items:
            res, rows = run_pg(conn, item["SQL"])
            qid = item["question_id"]
            got[qid] = {k: res.get(k) for k in ("row_count", "result_hash")}
            preview = rows[0] if rows else None
            print(f"{qid} {item['difficulty']:11s} {res['status']:6s} "
                  f"rows={res.get('row_count', 0):<4} {preview}")
            if res["status"] != "ok":
                failures.append(f"{qid}: {res['status']} {res.get('error', '')}")
            elif not freeze and expected.get(qid) != got[qid]:
                failures.append(f"{qid}: result differs from expected.json")
    print(dict(collections.Counter(i["difficulty"] for i in items)))
    if freeze and not failures:
        exp_path.write_text(json.dumps(got, indent=1) + "\n")
        print(f"froze {len(got)} results -> {exp_path}")
    for f in failures:
        print("FAIL", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main("--freeze" in sys.argv))
