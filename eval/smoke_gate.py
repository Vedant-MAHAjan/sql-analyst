"""CI regression gate: 60-question stratified smoke set vs a stored baseline.

  python -m eval.smoke_gate            # exit 1 if >= 4 questions regress
  python -m eval.smoke_gate --update   # accept the current results as the baseline

One question is ~1.7 points on 60, so a smaller drop is within noise.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from eval.runner import run

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "eval/configs/agent_evidence.yaml"
BASELINE = ROOT / "reports/smoke_baseline.json"
N, SEED, MAX_REGRESSIONS = 60, 0, 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--keep-run", action="store_true")
    args = ap.parse_args()
    run_dir = run(yaml.safe_load(open(CONFIG)), N, SEED)
    rows = [json.loads(line) for line in open(run_dir / "log.jsonl")]
    current = {f"{r['question_id']}#{i}": r["correct"] for i, r in enumerate(rows)}
    if not args.keep_run:
        shutil.rmtree(run_dir)
    if args.update or not BASELINE.exists():
        BASELINE.write_text(json.dumps(current, indent=1) + "\n")
        print(f"baseline written: {sum(current.values())}/{len(current)} correct")
        return 0
    base = json.loads(BASELINE.read_text())
    regressed = sorted(q for q in base if base[q] == 1 and current.get(q) == 0)
    improved = sorted(q for q in base if base[q] == 0 and current.get(q) == 1)
    print(f"smoke set: {sum(current.values())}/{len(current)} correct "
          f"(baseline {sum(base.values())}); regressed {len(regressed)}, improved {len(improved)}")
    if regressed:
        print("regressed:", ", ".join(regressed))
    if len(regressed) >= MAX_REGRESSIONS:
        print(f"FAIL: {len(regressed)} regressions (limit {MAX_REGRESSIONS - 1})")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
