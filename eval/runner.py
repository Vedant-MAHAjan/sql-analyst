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

from agent import baseline, generate, linker, pipeline, schema_index
from agent.llm import Completion, make_client
from agent.schema import ddl, tables_for
from eval import evaluator
from eval.db import ANALYST_DSNS, DSNS, connect

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
    n = len(rows)
    out["first_attempt"] = {
        "ex": round(100 * sum(r["correct_first"] for r in rows) / n, 2),
        "exec_error_rate": round(100 * sum(bool(r["error_type_first"]) for r in rows) / n, 2),
    }
    if any("attempts" in r for r in rows):
        out["abstain_rate"] = round(100 * sum(bool(r.get("abstain")) for r in rows) / n, 2)
        by_type: dict[str, dict] = {}
        for r in rows:
            t = r["error_type_first"]
            if not t:
                continue
            d = by_type.setdefault(t, {"n": 0, "fixed_exec": 0, "fixed_correct": 0})
            d["n"] += 1
            d["fixed_exec"] += not r["error_type"] and not r.get("abstain")
            d["fixed_correct"] += r["correct"]
        out["repair"] = dict(sorted(by_type.items(), key=lambda kv: -kv[1]["n"]))
    return out


def prompt_version(cfg: dict) -> str:
    link_cfg = cfg.get("linking")
    if cfg.get("agent"):
        base = generate.PROMPT_VERSION
    elif not link_cfg:
        return baseline.PROMPT_VERSION
    else:
        base = "linked-v1"
    return base + ("-desc" if link_cfg and link_cfg.get("describe") else "")


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


def cached_chat(client, model_cfg: dict, messages: list[dict]) -> Completion:
    key = _hash([model_cfg, messages, generate.OUTPUT_SCHEMA])
    path = RUNS / "cache" / f"{key}.json"
    if path.exists():
        return Completion(**json.loads(path.read_text()))
    comp = client.chat(messages, generate.OUTPUT_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comp.__dict__))
    return comp


def _baseline_question(client, cfg, conn, schema, it, evidence) -> dict:
    user = baseline.build_prompt(schema, it["question"], evidence)
    comp = cached_complete(client, cfg["model"], baseline.SYSTEM, user)
    sql = baseline.parse_sql(comp.text)
    pred = evaluator.execute(conn, sql) if sql else evaluator.Exec(
        "error", error_type="no_sql")
    return {"sql": sql, "pred": pred, "first": pred, "input_tokens": comp.input_tokens,
            "output_tokens": comp.output_tokens, "cost_usd": comp.cost_usd,
            "latency_s": comp.latency_s + pred.ms / 1000, "retries": 0}


def _agent_question(client, cfg, conn, exec_conn, schema, it, evidence) -> dict:
    agent_cfg = cfg["agent"]
    res = pipeline.answer(
        lambda msgs: cached_chat(client, cfg["model"], msgs), exec_conn,
        set(tables_for(conn, it["db_id"])), schema, it["question"], evidence,
        repair_max=agent_cfg.get("repair_max", 2),
        validate_sql=agent_cfg.get("validate", True))

    def as_exec(att: pipeline.Attempt) -> evaluator.Exec:
        return att.exec or evaluator.Exec("error", error_type=att.error_type or att.status,
                                          error=att.error)
    final, first = res.final, res.attempts[0]
    return {"sql": final.sql, "pred": as_exec(final), "first": as_exec(first),
            "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
            "cost_usd": 0.0, "latency_s": res.llm_s + res.exec_s,
            "retries": len(res.attempts) - 1, "abstain": final.status == "abstain",
            "assumptions": res.assumptions,
            "attempts": [{"sql": a.sql, "status": a.status, "error_type": a.error_type,
                          "error": a.error} for a in res.attempts]}


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
    with connect(DSNS[db], read_only=True) as conn, \
            connect(ANALYST_DSNS[db]) as exec_conn, \
            open(out_dir / "log.jsonl", "w") as log:
        for i, it in enumerate(items):
            evidence = it.get("evidence") if cfg.get("evidence") else None
            schema = build_schema(conn, cfg, it, evidence, schemas)
            if cfg.get("agent"):
                q = _agent_question(client, cfg, conn, exec_conn, schema, it, evidence)
            else:
                q = _baseline_question(client, cfg, conn, schema, it, evidence)
            gold = evaluator.execute(conn, it["SQL"])
            s = evaluator.score(q["pred"], gold.rows)
            first = evaluator.score(q["first"], gold.rows)
            row = {
                "run_id": run_id, "config_hash": config_hash,
                "model": cfg["model"]["model"], "prompt_version": version,
                "question_id": it["question_id"], "db_id": it["db_id"],
                "difficulty": it["difficulty"], "evidence": bool(evidence),
                "sql": q["sql"], "correct": s["ex"], "ex_tol": s["ex_tol"],
                "soft_f1": round(s["soft_f1"], 6), "error_type": q["pred"].error_type,
                "error": q["pred"].error, "input_tokens": q["input_tokens"],
                "output_tokens": q["output_tokens"], "cost_usd": q["cost_usd"],
                "latency_s": round(q["latency_s"], 3), "retries": q["retries"],
                "schema_chars": len(schema),
                "correct_first": first["ex"], "error_type_first": q["first"].error_type,
            }
            for k in ("abstain", "assumptions", "attempts"):
                if k in q:
                    row[k] = q[k]
            log.write(json.dumps(row, default=str) + "\n")
            log.flush()
            rows.append(row)
            print(f"[{i + 1}/{len(items)}] {it['question_id']} ex={s['ex']} "
                  f"{q['pred'].error_type or 'ok'} retries={q['retries']} "
                  f"{row['latency_s']}s", flush=True)
    (out_dir / "predict.json").write_text(json.dumps(
        {str(i): f"{r['sql']}{SEP}{r['db_id']}" for i, r in enumerate(rows)}, indent=1))
    summary = summarize(rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary["all"]), json.dumps(summary["error_types"]))
    if "repair" in summary:
        print(json.dumps(summary["repair"]))
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    print(run(yaml.safe_load(open(args.config)), args.sample, args.seed))
