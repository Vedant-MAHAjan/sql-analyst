"""Freeze every prompt before the held-out run; verify nothing changed after.

Usage: python -m eval.freeze write | check
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from agent import answer, baseline, generate, llm_linker, multi

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "reports/phase6/frozen_prompts.json"
PROMPTS = {
    "baseline.SYSTEM": baseline.SYSTEM,
    "generate.SYSTEM": generate.SYSTEM,
    "generate.GUARD": generate.GUARD,
    "answer.SUMMARY_SYSTEM": answer.SUMMARY_SYSTEM,
    "llm_linker.SYSTEM": llm_linker.SYSTEM,
    "multi.PLANNER_SYSTEM": multi.PLANNER_SYSTEM,
    "multi.CRITIC_SYSTEM": multi.CRITIC_SYSTEM,
}


def digests() -> dict[str, str]:
    return {k: hashlib.sha256(v.encode()).hexdigest() for k, v in PROMPTS.items()}


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        FROZEN.parent.mkdir(parents=True, exist_ok=True)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                cwd=ROOT).stdout.strip()
        FROZEN.write_text(json.dumps({"base_commit": commit, "sha256": digests()}, indent=1) + "\n")
        print(f"froze {len(PROMPTS)} prompts -> {FROZEN}")
    elif sys.argv[1:] == ["check"]:
        frozen = json.loads(FROZEN.read_text())["sha256"]
        changed = [k for k, v in digests().items() if frozen.get(k) != v]
        print("prompts unchanged since freeze" if not changed else f"CHANGED: {changed}")
        sys.exit(1 if changed else 0)
