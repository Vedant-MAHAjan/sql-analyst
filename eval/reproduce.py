"""Rebuild the headline table from committed predictions.

  python -m eval.reproduce          # re-execute and re-score data/run_logs/*
  python -m eval.reproduce --pack   # (maintainers) refresh data/run_logs from runs/

No model is called: each run's saved SQL is executed against the database as the
read-only role and scored again. Exits 1 if any EX score differs from the log.
"""
import gzip
import json
import shutil
import sys
from pathlib import Path

import yaml

from eval import evaluator, report
from eval.db import ANALYST_DSNS, DSNS, connect
from eval.passk import passk
from eval.runner import load_items, summarize

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "reports/phase6/manifest.yaml"
LOGS = ROOT / "data/run_logs"
REPLAY = ROOT / "runs/replay"


def replay(run_id: str, dataset: str) -> tuple[Path, list]:
    with gzip.open(LOGS / f"{run_id}.jsonl.gz", "rt") as fh:
        rows = [json.loads(line) for line in fh]
    items, db = load_items(dataset)
    gold_sql = {it["question_id"]: it["SQL"] for it in items}
    changed = []
    with connect(DSNS[db], read_only=True) as admin, connect(ANALYST_DSNS[db]) as run:
        for r in rows:
            # A query that failed or was rejected in the run stays failed.
            pred = evaluator.Exec("error", error_type=r["error_type"]) if r["error_type"] \
                or r.get("abstain") or not r["sql"] else evaluator.execute(run, r["sql"])
            s = evaluator.score(pred, evaluator.execute(admin, gold_sql[r["question_id"]]).rows)
            if s["ex"] != r["correct"]:
                changed.append((run_id, r["question_id"], r["correct"], s["ex"]))
            r.update(correct=s["ex"], ex_tol=s["ex_tol"], soft_f1=round(s["soft_f1"], 6))
    out = REPLAY / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "log.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(summarize(rows), indent=1) + "\n")
    return out, changed


def pack(manifest: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    def latest(name: str, n: int) -> Path:
        dirs = [d for d in sorted((ROOT / "runs").glob(f"{name}-2*"))
                if (d / "summary.json").exists()
                and sum(1 for _ in open(d / "log.jsonl")) == n]
        return dirs[-1]
    targets = {}
    for item in manifest["runs"]:
        cfg = yaml.safe_load(open(ROOT / item["config"]))
        n = item.get("sample") or (40 if cfg["dataset"] == "heldout" else 500)
        targets[item["id"]] = latest(cfg["name"], n)
    for seed in manifest["passk"]["seeds"]:
        targets[f"passk_seed{seed}"] = latest(
            f"agent-evidence-temperature{manifest['passk']['temperature']}-seed{seed}",
            manifest["passk"]["sample"])
    for run_id, d in targets.items():
        with open(d / "log.jsonl", "rb") as src, gzip.GzipFile(
                LOGS / f"{run_id}.jsonl.gz", "wb", mtime=0) as dst:
            shutil.copyfileobj(src, dst)
        print(run_id, "<-", d.name)


def main() -> int:
    manifest = yaml.safe_load(open(MANIFEST))
    if "--pack" in sys.argv:
        pack(manifest)
        return 0
    dirs, entries, changed = {}, [], []
    for item in manifest["runs"]:
        d, diff = replay(item["id"], item.get("dataset", "bird"))
        changed += diff
        dirs[item["id"]] = str(d.relative_to(ROOT))
        entries.append({**item, "run": dirs[item["id"]],
                        **({"vs": dirs[item["vs"]]} if item.get("vs") else {})})
        print(f"{item['id']}: EX {summarize_ex(d)}", flush=True)
    report.headline(entries, manifest.get("notes"))
    runs = []
    for seed in manifest["passk"]["seeds"]:
        d, diff = replay(f"passk_seed{seed}", "bird")
        changed += diff
        runs.append(str(d))
    out = passk(runs)
    (report.OUT / "passk.json").write_text(json.dumps(out, indent=1) + "\n")
    for c in changed:
        print("CHANGED", c)
    print(f"{len(changed)} scores differ from the saved runs")
    return 1 if changed else 0


def summarize_ex(d: Path) -> float:
    return json.loads((d / "summary.json").read_text())["all"]["ex"]


if __name__ == "__main__":
    sys.exit(main())
