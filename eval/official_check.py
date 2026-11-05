"""Check that our evaluator agrees with BIRD's official scripts, per question.

Usage:
  python -m eval.official_check --synthetic       # mutated gold predictions
  python -m eval.official_check runs/<run_id>     # a run's predict.json
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from eval import evaluator
from eval.db import DSN, connect

ROOT = Path(__file__).resolve().parent.parent
MINIDEV = ROOT / "data/raw/minidev/minidev/MINIDEV"
VENDORED = ROOT / "data/raw/bird_eval"
OFFICIAL_PY = ROOT / ".venv-official/bin/python"
SEP = "\t----- bird -----\t"


def synthetic(items: list[dict]) -> list[str]:
    """Gold, and gold mutated in ways that sometimes change the result."""
    preds = []
    for i, it in enumerate(items):
        sql = it["SQL"].strip().rstrip(";")
        kind = i % 5
        if kind == 1 and "LIMIT" not in sql.upper():
            sql += " LIMIT 1"
        elif kind == 2 and not sql.upper().startswith("SELECT DISTINCT"):
            sql = sql.replace("SELECT ", "SELECT DISTINCT ", 1)
        elif kind == 3:
            sql = sql.replace("SELECT", "SELEC", 1)
        elif kind == 4:
            same_db = [x for x in items if x["db_id"] == it["db_id"] and x is not it]
            sql = same_db[i % len(same_db)]["SQL"]
        preds.append(sql)
    return preds


def ours(items: list[dict], preds: list[str]) -> tuple[list, list]:
    ex, f1 = [], []
    with connect(DSN, read_only=True) as conn:
        for it, sql in zip(items, preds):
            gold = evaluator.execute(conn, it["SQL"])
            s = evaluator.score(evaluator.execute(conn, sql), gold.rows)
            ex.append(s["ex"])
            f1.append(s["soft_f1"])
    return ex, f1


def official(items: list[dict], preds: list[str], metric: str) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        pred_path, diff_path = Path(tmp, "pred.json"), Path(tmp, "diff.jsonl")
        pred_path.write_text(json.dumps(
            {str(i): f"{sql}{SEP}{it['db_id']}" for i, (it, sql) in enumerate(zip(items, preds))}
        ))
        diff_path.write_text("".join(json.dumps(it) + "\n" for it in items))
        out = subprocess.run(
            [str(OFFICIAL_PY), str(ROOT / "eval/_official_wrapper.py"), metric,
             str(VENDORED), DSN.replace("postgresql://", "postgres://"),
             "--predicted_sql_path", str(pred_path),
             "--ground_truth_path", str(MINIDEV / "mini_dev_postgresql_gold.sql"),
             "--db_root_path", str(MINIDEV / "dev_databases") + "/",
             "--diff_json_path", str(diff_path), "--sql_dialect", "PostgreSQL",
             "--num_cpus", "8", "--output_log_path", str(Path(tmp, "log.txt"))],
            check=True, capture_output=True, text=True,
        )
        return json.loads(out.stdout)


def main(argv: list[str]) -> int:
    items = json.loads((MINIDEV / "mini_dev_postgresql.json").read_text())
    if argv and argv[0] == "--synthetic":
        preds = synthetic(items)
    else:
        raw = json.loads(Path(argv[0], "predict.json").read_text())
        preds = [raw[str(i)].split(SEP)[0] for i in range(len(items))]
    our_ex, our_f1 = ours(items, preds)
    off_ex, off_f1 = official(items, preds, "ex"), official(items, preds, "f1")
    ex_diff = [i for i, (a, b) in enumerate(zip(our_ex, off_ex)) if a != b]
    f1_diff = [i for i, (a, b) in enumerate(zip(our_f1, off_f1)) if abs(a - b) > 1e-9]
    n = len(items)
    print(f"EX       ours {100 * sum(our_ex) / n:.2f}  official {100 * sum(off_ex) / n:.2f}"
          f"  per-question disagreements: {len(ex_diff)}")
    print(f"Soft-F1  ours {100 * sum(our_f1) / n:.2f}  official {100 * sum(off_f1) / n:.2f}"
          f"  per-question disagreements: {len(f1_diff)}")
    for i in (ex_diff + f1_diff)[:10]:
        print(f"  idx {i} qid {items[i]['question_id']}: ex {our_ex[i]}/{off_ex[i]}"
              f" f1 {our_f1[i]:.4f}/{off_f1[i]:.4f}")
    return 1 if ex_diff or f1_diff else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
