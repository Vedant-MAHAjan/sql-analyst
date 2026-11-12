"""Phase 2 metric: does the linked schema contain every column the gold SQL uses?

Usage: python -m eval.schema_recall [--mode table|column] [--no-evidence] [key=value ...]
"""
import argparse
import json
import statistics
import warnings

from agent import linker, schema_index
from agent.schema import ddl
from eval.db import DSNS, connect
from eval.gold_columns import referenced_columns, schema_map
from agent.llm import make_client
from eval.runner import llm_tables, load_items

warnings.filterwarnings("ignore")  # sqlglot qualify warnings on unknown names


def measure(dataset: str, cfg: linker.LinkerConfig, evidence: bool, verbose: int = 0,
            describe: bool = False, llm_cfg: dict | None = None) -> dict:
    llm_client = make_client(llm_cfg) if llm_cfg else None
    items, db = load_items(dataset)
    rows, misses = [], []
    with connect(DSNS[db], read_only=True) as conn:
        maps, full = {}, {}
        for it in items:
            db_id = it["db_id"]
            ix = schema_index.build(conn, db_id)
            if db_id not in maps:
                maps[db_id] = schema_map(conn, list(ix.tables))
                full[db_id] = len(ddl(conn, db_id))
            gold = referenced_columns(it["SQL"], maps[db_id])
            ev = it.get("evidence", "") if evidence else ""
            extra = None
            if llm_client:  # tiered linking; same cache as the runner
                extra = llm_tables(conn, {"llm_linker": llm_cfg}, llm_client, it, ev or None)
            lk = linker.link(conn, db_id, it["question"], ev, cfg, extra_tables=extra)
            got = {(t, c) for t, cols in lk.selection.items()
                   for c in (ix.tables[t].columns if cols is None else cols)}
            got_tables = set(lk.selection)
            missing = {gc for gc in gold if gc[1] != "*" and gc not in got}
            missing |= {gc for gc in gold if gc[1] == "*" and gc[0] not in got_tables}
            size = len(ix.render(lk.selection, lk.value_hits, describe=describe))
            rows.append({"col_ok": not missing,
                         "table_ok": {t for t, _ in gold} <= got_tables,
                         "size": size, "full": full[db_id],
                         "tables": len(got_tables), "all_tables": len(ix.tables),
                         "difficulty": it["difficulty"]})
            if missing:
                misses.append((it["question_id"], sorted(missing), it["question"][:80]))
    n = len(rows)
    out = {
        "n": n,
        "column_recall": round(100 * sum(r["col_ok"] for r in rows) / n, 1),
        "table_recall": round(100 * sum(r["table_ok"] for r in rows) / n, 1),
        "mean_chars": round(statistics.mean(r["size"] for r in rows)),
        "mean_chars_whole_schema": round(statistics.mean(r["full"] for r in rows)),
        "size_ratio": round(sum(r["size"] for r in rows) / sum(r["full"] for r in rows), 3),
        "mean_tables": round(statistics.mean(r["tables"] for r in rows), 2),
        "mean_all_tables": round(statistics.mean(r["all_tables"] for r in rows), 2),
    }
    for d in ("simple", "moderate", "challenging"):
        rs = [r for r in rows if r["difficulty"] == d]
        out[f"column_recall_{d}"] = round(100 * sum(r["col_ok"] for r in rs) / len(rs), 1)
    for m in misses[:verbose]:
        print("  miss", m)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="bird")
    ap.add_argument("--no-evidence", action="store_true")
    ap.add_argument("--verbose", type=int, default=0)
    ap.add_argument("--describe", action="store_true", help="size with BIRD descriptions")
    ap.add_argument("--llm-linker", help="Ollama model that also names tables, e.g. qwen2.5-coder:7b")
    ap.add_argument("overrides", nargs="*", help="LinkerConfig field=value")
    args = ap.parse_args()
    cfg = linker.LinkerConfig()
    for kv in args.overrides:
        k, v = kv.split("=")
        setattr(cfg, k, type(getattr(cfg, k))(v))
    print(json.dumps({"config": cfg.__dict__, "evidence": not args.no_evidence,
                      **measure(args.dataset, cfg, not args.no_evidence, args.verbose, args.describe,
                               {"provider": "ollama", "model": args.llm_linker,
                                "options": {"temperature": 0.0, "seed": 0, "num_ctx": 8192}}
                               if args.llm_linker else None)}))
