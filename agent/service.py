"""The agent behind the API and the MCP server: question in, SQL + answer + chart out."""
import re
import time
from pathlib import Path

import yaml

from agent import answer, generate, linker, pipeline, schema_index
from agent.execute import execute_any, execute_capped
from agent.llm import make_client
from agent.schema import bird_tables, ddl, tables_for
from eval.db import ANALYST_DSNS, DSNS, connect

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "serve/config.yaml"
DISPLAY_ROWS = 200
WRITE_REFUSAL = "I can't do that: I can only read data, not change it."
WRITE_WORDS = re.compile(r"\b(delete|drop|remove|update|insert|add|create|change|set|"
                         r"rename|truncate|alter|grant|lock|modify)\b", re.I)


class Agent:
    """Layers can be switched off for the attack suite; the database role cannot."""

    def __init__(self, config_path: Path = CONFIG, prompt_guard: bool | None = None,
                 validate: bool | None = None, databases: dict[str, str] | None = None,
                 cursor_only: bool = True, grounding: bool | None = None):
        self.cfg = yaml.safe_load(open(config_path))
        self.client = make_client(self.cfg["model"])
        self.max_rows = self.cfg.get("max_rows", 1000)
        self.prompt_guard = self.cfg.get("prompt_guard", True) if prompt_guard is None \
            else prompt_guard
        self.validate = self.cfg.get("validate", True) if validate is None else validate
        # Output-side check: a summary that states no value from the result is replaced
        # by a plain readout (planted text can hijack the summary, not the rows).
        self.grounding = self.cfg.get("grounding", True) if grounding is None else grounding
        # Logical group -> physical database (the attack suite points at clones).
        self.dbmap = databases or {"bird": "bird", "pagila": "pagila"}
        # A server-side cursor only accepts SELECT; cursor_only=False removes that
        # incidental filter so the attack suite can test the database role alone.
        self.execute = execute_capped if cursor_only else execute_any

    def databases(self) -> list[str]:
        return ["pagila", *sorted(bird_tables())]

    def _group(self, db_id: str) -> str:
        if db_id == "pagila":
            return "pagila"
        if db_id in bird_tables():
            return "bird"
        raise KeyError(f"unknown database {db_id!r}")

    def describe_schema(self, db_id: str) -> dict:
        with connect(DSNS[self.dbmap[self._group(db_id)]], read_only=True) as conn:
            return {"database": db_id, "tables": tables_for(conn, db_id),
                    "ddl": ddl(conn, db_id)}

    def ask(self, db_id: str, question: str, evidence: str | None = None) -> dict:
        start = time.perf_counter()
        physical = self.dbmap[self._group(db_id)]
        with connect(DSNS[physical], read_only=True) as meta, \
                connect(ANALYST_DSNS[physical]) as run:
            lk = linker.link(meta, db_id, question, evidence or "",
                             linker.LinkerConfig(**self.cfg.get("linking", {})))
            schema = schema_index.build(meta, db_id).render(lk.selection, lk.value_hits,
                                                            describe=False)
            res = pipeline.answer(
                lambda msgs: self.client.chat(msgs, generate.OUTPUT_SCHEMA), run,
                set(tables_for(meta, db_id)), schema, question, evidence,
                repair_max=self.cfg.get("repair_max", 2), validate_sql=self.validate,
                execute_fn=lambda c, s: self.execute(c, s, self.max_rows),
                system=generate.SYSTEM_GUARDED if self.prompt_guard else generate.SYSTEM)
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
            out["answer"] = (WRITE_REFUSAL if WRITE_WORDS.search(question)
                             else "I can't answer that from this database.")
        elif final.status == "ok":
            ex = final.exec
            out.update(columns=ex.columns, row_count=len(ex.rows), truncated=ex.truncated,
                       rows=[[answer.jsonable(v) for v in r] for r in ex.rows[:DISPLAY_ROWS]],
                       chart=answer.chart_spec(ex.columns, ex.rows))
            comp = self.client.chat([
                {"role": "system", "content": answer.SUMMARY_SYSTEM if self.prompt_guard
                 else answer.SUMMARY_SYSTEM_PLAIN},
                {"role": "user", "content": answer.summary_prompt(
                    question, final.sql, ex.columns, ex.rows, ex.truncated)}])
            out["answer"] = comp.text.strip()
            llm_s += comp.latency_s
            if self.grounding and ex.rows and not answer.grounded(out["answer"], ex.rows):
                out["answer"] = answer.template_answer(ex.columns, ex.rows, ex.truncated)
                out["answer_source"] = "template"
        else:
            out["answer"] = "The query could not be run after repair attempts."
        out["timings"] = {"llm_s": round(llm_s, 2), "exec_s": round(res.exec_s, 3),
                          "total_s": round(time.perf_counter() - start, 2)}
        return out
