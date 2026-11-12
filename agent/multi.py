"""Planner + critic ablation: plan -> generate (with repair) -> critique -> one revision.

Tested against the single agent instead of assumed to help.
"""
import json
from dataclasses import dataclass

from agent import pipeline
from agent.answer import jsonable

PROMPT_VERSION = "planner-critic-v1"
PLANNER_SYSTEM = (
    "You are a senior analyst planning a SQL query. Given a database schema, a question "
    "and an optional hint, write a short plan: which tables and join path, which filters "
    "(with exact values), what to compute or aggregate and at what level, and which "
    "columns to output in which order. Do not write SQL. Respond with JSON: {\"plan\": \"...\"}."
)
CRITIC_SYSTEM = (
    "You review a PostgreSQL query written to answer a question. You see the question, "
    "the hint, the query and the first rows of its result. Check that it answers exactly "
    "what was asked: the right columns in the right order, the right filters, the right "
    "aggregation level and join path, and correct use of the hint. Respond with JSON: "
    "{\"verdict\": \"ok\" or \"revise\", \"problem\": \"...\"}. Say \"revise\" only for a "
    "concrete error you can name."
)
PLAN_SCHEMA = {"type": "object", "properties": {"plan": {"type": "string"}},
               "required": ["plan"]}
CRITIC_SCHEMA = {"type": "object",
                 "properties": {"verdict": {"type": "string", "enum": ["ok", "revise"]},
                                "problem": {"type": "string"}},
                 "required": ["verdict", "problem"]}


@dataclass
class Review:
    plan: str
    verdict: str = ""
    problem: str = ""
    revised: bool = False
    kept_revision: bool = False


def _json(text: str, key: str) -> str:
    try:
        return str(json.loads(text).get(key) or "")
    except (json.JSONDecodeError, AttributeError):
        return ""


def _preview(ex, rows: int = 10) -> str:
    shown = [[str(jsonable(v))[:100] for v in r] for r in ex.rows[:rows]]
    return json.dumps({"columns": ex.columns or None, "rows": shown, "total_rows": len(ex.rows)})


def answer(chat, conn, allowed, schema_text, question, evidence, **kwargs):
    """chat(messages, schema) -> Completion. Returns (pipeline.Result, Review)."""
    hint = f"Hint: {evidence}\n\n" if evidence else ""
    plan_comp = chat([{"role": "system", "content": PLANNER_SYSTEM},
                      {"role": "user", "content": f"Database schema:\n{schema_text}\n\n"
                                                  f"{hint}Question: {question}"}], PLAN_SCHEMA)
    review = Review(plan=_json(plan_comp.text, "plan"))
    res = pipeline.answer(lambda m: chat(m, None), conn, allowed, schema_text, question,
                          evidence, plan=review.plan, **kwargs)
    extra_in, extra_out, extra_s = plan_comp.input_tokens, plan_comp.output_tokens, plan_comp.latency_s
    final = res.final
    if final.status == "ok":
        crit = chat([{"role": "system", "content": CRITIC_SYSTEM},
                     {"role": "user", "content": f"Question: {question}\n\n{hint}Query:\n"
                                                 f"{final.sql}\n\nResult:\n{_preview(final.exec)}"}],
                    CRITIC_SCHEMA)
        extra_in, extra_out, extra_s = (extra_in + crit.input_tokens,
                                        extra_out + crit.output_tokens, extra_s + crit.latency_s)
        review.verdict = _json(crit.text, "verdict")
        review.problem = _json(crit.text, "problem")
        if review.verdict == "revise" and review.problem:
            review.revised = True
            feedback = (f"{review.plan}\n\nA reviewer checked an earlier query:\n{final.sql}\n"
                        f"Problem found: {review.problem}\nAvoid that problem.")
            res2 = pipeline.answer(lambda m: chat(m, None), conn, allowed, schema_text,
                                   question, evidence, plan=feedback, **kwargs)
            for k in ("input_tokens", "output_tokens", "llm_s", "exec_s"):
                setattr(res, k, getattr(res, k) + getattr(res2, k))
            if res2.final.status == "ok":
                res.attempts += res2.attempts
                review.kept_revision = True
    res.input_tokens += extra_in
    res.output_tokens += extra_out
    res.llm_s += extra_s
    return res, review
