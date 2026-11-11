"""The agent behind the API and the MCP server: question in, SQL + answer + chart out."""
import time
from pathlib import Path

import yaml

from agent import answer, generate, linker, pipeline, schema_index
from agent.execute import execute_capped
from agent.llm import make_client
from agent.schema import bird_tables, ddl, tables_for
from eval.db import ANALYST_DSNS, DSNS, connect

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "serve/config.yaml"
DISPLAY_ROWS = 200


class Agent:
    def __init__(self, config_path: Path = CONFIG):
        self.cfg = yaml.safe_load(open(config_path))
        self.client = make_client(self.cfg["model"])
        self.max_rows = self.cfg.get("max_rows", 1000)

    def databases(self) -> list[str]:
        return ["pagila", *sorted(bird_tables())]

    def _group(self, db_id: str) -> str:
        if db_id == "pagila":
            return "pagila"
        if db_id in bird_tables():
            return "bird"
        raise KeyError(f"unknown database {db_id!r}")

    def describe_schema(self, db_id: str) -> dict:
        with connect(DSNS[self._group(db_id)], read_only=True) as conn:
            return {"database": db_id, "tables": tables_for(conn, db_id),
                    "ddl": ddl(conn, db_id)}

    def ask(self, db_id: str, question: str, evidence: str | None = None) -> dict:
        start = time.perf_counter()
        group = self._group(db_id)
        with connect(DSNS[group], read_only=True) as meta, connect(ANALYST_DSNS[group]) as run:
            lk = linker.link(meta, db_id, question, evidence or "",
                             linker.LinkerConfig(**self.cfg.get("linking", {})))
            schema = schema_index.build(meta, db_id).render(lk.selection, lk.value_hits,
                                                            describe=False)
            res = pipeline.answer(
                lambda msgs: self.client.chat(msgs, generate.OUTPUT_SCHEMA), run,
                set(tables_for(meta, db_id)), schema, question, evidence,
                repair_max=self.cfg.get("repair_max", 2),
                execute_fn=lambda c, s: execute_capped(c, s, self.max_rows))
        final = res.final
        out = {
            "database": db_id, "question": question, "sql": final.sql,
            "assumptions": res.assumptions, "status": final.status, "error": final.error,
            "linked_tables": sorted(lk.selection),
            "attempts": [{"status": a.status, "error_type": a.error_type, "error": a.error,
                          "sql": a.sql} for a in res.attempts],
            "columns": [], "rows": [], "row_count": 0, "truncated": False,
            "answer": "", "chart": {"type": "table"},
        }
        llm_s = res.llm_s
        if final.status == "abstain":
            out["answer"] = "I can't answer that from this database's schema."
        elif final.status == "ok":
            ex = final.exec
            out.update(columns=ex.columns, row_count=len(ex.rows), truncated=ex.truncated,
                       rows=[[answer.jsonable(v) for v in r] for r in ex.rows[:DISPLAY_ROWS]],
                       chart=answer.chart_spec(ex.columns, ex.rows))
            comp = self.client.chat([
                {"role": "system", "content": answer.SUMMARY_SYSTEM},
                {"role": "user", "content": answer.summary_prompt(
                    question, final.sql, ex.columns, ex.rows, ex.truncated)}])
            out["answer"] = comp.text.strip()
            llm_s += comp.latency_s
        else:
            out["answer"] = "The query could not be run after repair attempts."
        out["timings"] = {"llm_s": round(llm_s, 2), "exec_s": round(res.exec_s, 3),
                          "total_s": round(time.perf_counter() - start, 2)}
        return out
