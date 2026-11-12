"""Rebuild the headline table from the committed model-call cache.

  python -m eval.reproduce            # re-score every config in reports/phase6/manifest.yaml

Model outputs come from runs/cache (unpacked from data/model_cache.tar.gz by
`make reproduce`), so this needs Docker and the data but not Ollama or a GPU:
the SQL is re-executed and re-scored, and the table is rebuilt exactly. A
missing cache entry falls back to calling the model.
"""
import json
from pathlib import Path

import yaml

from eval import report
from eval.passk import passk
from eval.runner import run

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "reports/phase6/manifest.yaml"


def main() -> None:
    manifest = yaml.safe_load(open(MANIFEST))
    dirs: dict[str, str] = {}
    entries = []
    for item in manifest["runs"]:
        cfg = yaml.safe_load(open(ROOT / item["config"]))
        run_dir = run(cfg, item.get("sample"), item.get("seed", 0))
        dirs[item["id"]] = str(run_dir.relative_to(ROOT))
        entries.append({**item, "run": dirs[item["id"]],
                        **({"vs": dirs[item["vs"]]} if item.get("vs") else {})})
    report.headline(entries, manifest.get("notes"))
    if manifest.get("passk"):
        pk = manifest["passk"]
        runs = []
        for seed in pk["seeds"]:
            cfg = yaml.safe_load(open(ROOT / pk["config"]))
            cfg["model"]["options"].update(temperature=pk["temperature"], seed=seed)
            cfg["name"] += f"-temperature{pk['temperature']}-seed{seed}"
            runs.append(str(run(cfg, pk["sample"], 0)))
        out = passk(runs)
        (report.OUT / "passk.json").write_text(json.dumps(out, indent=1) + "\n")
        print(json.dumps(out))


if __name__ == "__main__":
    main()
