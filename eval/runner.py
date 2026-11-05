"""Run one config over a dataset, score it, and write a run directory.

Usage:
  python -m eval.runner eval/configs/baseline.yaml [--sample N] [--seed S]

Writes runs/<run_id>/{config.yaml, log.jsonl, predict.json, summary.json}.
Model calls are cached by a hash of (model config, full prompt), so rerunning
an unchanged config costs nothing.
"""
import argparse
import datetime as dt
import hashlib
import json
import random
import statistics
from pathlib import Path

import yaml

from agent import baseline, linker, schema_index
from agent.llm import Completion, make_client
from agent.schema import ddl
from eval import evaluator
from eval.db import DSNS, connect

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
DATASETS = {
    "bird": (ROOT / "data/raw/minidev/minidev/MINIDEV/mini_dev_postgresql.json", "bird"),
    "heldout": (ROOT / "data/heldout/questions.jsonl", "pagila"),
}
SEP = "\t----- bird -----\t"
DIFFS = ("simple", "moderate", "challenging")


def load_items(dataset: str) -> tuple[list[dict], str]:
    path, db = DATASETS[dataset]
    text = path.read_text()
    items = json.loads(text) if path.suffix == ".json" else [
        json.loads(line) for line in text.splitlines() if line.strip()]
    return items, db


def stratified(items: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    picked = []
    for d in DIFFS:
        group = [it for it in items if it["difficulty"] == d]
        k = round(n * len(group) / len(items))
        picked += rng.sample(group, min(k, len(group)))
    order = {id(it): i for i, it in enumerate(items)}
    return sorted(picked, key=lambda it: order[id(it)])


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def cached_complete(client, model_cfg: dict, system: str, user: str) -> Completion:
    key = _hash([model_cfg, system, user])
    path = RUNS / "cache" / f"{key}.json"
    if path.exists():
        return Completion(**json.loads(path.read_text()))
    comp = client.complete(system, user, baseline.SQL_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comp.__dict__))
    return comp


def summarize(rows: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        if not rs:
            return {}
        lat = sorted(r["latency_s"] for r in rs)
        n = len(rs)
        return {
            "n": n,
            "ex": round(100 * sum(r["correct"] for r in rs) / n, 2),
            "ex_tol": round(100 * sum(r["ex_tol"] for r in rs) / n, 2),
            "soft_f1": round(100 * sum(r["soft_f1"] for r in rs) / n, 2),
            "exec_error_rate": round(100 * sum(bool(r["error_type"]) for r in rs) / n, 2),
            "latency_p50_s": round(statistics.median(lat), 2),
            "latency_p95_s": round(lat[min(n - 1, int(0.95 * n))], 2),
            "input_tokens_mean": round(sum(r["input_tokens"] for r in rs) / n),
            "output_tokens_mean": round(sum(r["output_tokens"] for r in rs) / n),
            "cost_usd": round(sum(r["cost_usd"] for r in rs), 4),
        }
    out = {"all": block(rows)}
    for d in DIFFS:
        out[d] = block([r for r in rows if r["difficulty"] == d])
    errors: dict[str, int] = {}
    for r in rows:
        if r["error_type"]:
            errors[r["error_type"]] = errors.get(r["error_type"], 0) + 1
    out["error_types"] = dict(sorted(errors.items(), key=lambda kv: -kv[1]))
    return out


def prompt_version(cfg: dict) -> str:
    link_cfg = cfg.get("linking")
    if not link_cfg:
        return baseline.PROMPT_VERSION
    return "linked-v1" + ("-desc" if link_cfg.get("describe") else "")


def build_schema(conn, cfg: dict, it: dict, evidence: str | None, whole: dict) -> str:
    link_cfg = cfg.get("linking")
    if not link_cfg:
        if it["db_id"] not in whole:
            whole[it["db_id"]] = ddl(conn, it["db_id"])
        return whole[it["db_id"]]
    opts = {k: v for k, v in link_cfg.items() if k != "describe"}
    lk = linker.link(conn, it["db_id"], it["question"], evidence or "",
                     linker.LinkerConfig(**opts))
    return schema_index.build(conn, it["db_id"]).render(
        lk.selection, lk.value_hits, describe=link_cfg.get("describe", False))


def run(cfg: dict, sample: int | None, seed: int) -> Path:
    items, db = load_items(cfg["dataset"])
    if sample:
        items = stratified(items, sample, seed)
    version = prompt_version(cfg)
    config_hash = _hash([cfg, version])
    run_id = f"{cfg['name']}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    out_dir = RUNS / run_id
    out_dir.mkdir(parents=True)
    (out_dir / "config.yaml").write_text(yaml.safe_dump(
        {**cfg, "sample": sample, "seed": seed, "config_hash": config_hash,
         "prompt_version": version}))
    client = make_client(cfg["model"])
    rows, schemas = [], {}
    with connect(DSNS[db], read_only=True) as conn, open(out_dir / "log.jsonl", "w") as log:
        for i, it in enumerate(items):
            evidence = it.get("evidence") if cfg.get("evidence") else None
            schema = build_schema(conn, cfg, it, evidence, schemas)
            user = baseline.build_prompt(schema, it["question"], evidence)
            comp = cached_complete(client, cfg["model"], baseline.SYSTEM, user)
            sql = baseline.parse_sql(comp.text)
            pred = evaluator.execute(conn, sql) if sql else evaluator.Exec(
                "error", error_type="no_sql")
            gold = evaluator.execute(conn, it["SQL"])
            s = evaluator.score(pred, gold.rows)
            row = {
                "run_id": run_id, "config_hash": config_hash,
                "model": cfg["model"]["model"], "prompt_version": version,
                "question_id": it["question_id"], "db_id": it["db_id"],
                "difficulty": it["difficulty"], "evidence": bool(evidence),
                "sql": sql, "correct": s["ex"], "ex_tol": s["ex_tol"],
                "soft_f1": round(s["soft_f1"], 6), "error_type": pred.error_type,
                "error": pred.error, "input_tokens": comp.input_tokens,
                "output_tokens": comp.output_tokens, "cost_usd": comp.cost_usd,
                "latency_s": round(comp.latency_s + pred.ms / 1000, 3), "retries": 0,
                "schema_chars": len(schema),
            }
            log.write(json.dumps(row) + "\n")
            log.flush()
            rows.append(row)
            print(f"[{i + 1}/{len(items)}] {it['question_id']} ex={s['ex']} "
                  f"{pred.error_type or 'ok'} {row['latency_s']}s", flush=True)
    (out_dir / "predict.json").write_text(json.dumps(
        {str(i): f"{r['sql']}{SEP}{r['db_id']}" for i, r in enumerate(rows)}, indent=1))
    summary = summarize(rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary["all"]), json.dumps(summary["error_types"]))
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    print(run(yaml.safe_load(open(args.config)), args.sample, args.seed))
