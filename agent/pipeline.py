"""Generate -> validate -> execute -> repair, for one question."""
from dataclasses import dataclass, field
from typing import Callable

import psycopg

from agent import generate
from agent.llm import Completion
from agent.validate import validate
from eval import evaluator


@dataclass
class Attempt:
    sql: str
    status: str  # ok | invalid | error | timeout | too_many_rows | no_sql | abstain
    error_type: str = ""
    error: str = ""
    exec: evaluator.Exec | None = None


@dataclass
class Result:
    attempts: list[Attempt] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    llm_s: float = 0.0
    exec_s: float = 0.0

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]


def _feedback(att: Attempt) -> str:
    if att.status == "no_sql":
        return "Error: the response contained no SQL."
    if att.status == "invalid":
        return f"Error: {att.error}"
    if att.status == "timeout":
        return "Error: the query timed out after 30 seconds. Write a simpler, faster query."
    if att.status == "too_many_rows":
        return "Error: the query returned far too many rows; it is probably missing a join condition."
    ex = att.exec
    return generate.error_context(att.sql, ex.error, ex.hint, ex.position)


def answer(chat: Callable[[list[dict]], Completion], conn: psycopg.Connection,
           allowed_tables: set[str], schema_text: str, question: str,
           evidence: str | None, repair_max: int = 2, validate_sql: bool = True,
           execute_fn: Callable = evaluator.execute,
           system: str = generate.SYSTEM) -> Result:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": generate.build_prompt(schema_text, question, evidence)},
    ]
    res = Result()
    for i in range(repair_max + 1):
        comp = chat(messages)
        res.input_tokens += comp.input_tokens
        res.output_tokens += comp.output_tokens
        res.llm_s += comp.latency_s
        out = generate.parse(comp.text)
        if i == 0:
            res.assumptions = out["assumptions"]
        sql = out["sql"]
        if out["abstain"]:
            res.attempts.append(Attempt("", "abstain"))
            break
        if not sql:
            att = Attempt("", "no_sql", "no_sql")
        else:
            v = validate(sql, allowed_tables) if validate_sql else None
            if v is not None and not v.ok:
                att = Attempt(sql, "invalid", f"invalid_{v.error_type}", v.message)
            else:
                ex = execute_fn(conn, sql)
                res.exec_s += ex.ms / 1000
                att = Attempt(sql, ex.status, ex.error_type, ex.error, ex)
        res.attempts.append(att)
        if att.status == "ok" or i == repair_max:
            break
        messages += [{"role": "assistant", "content": comp.text},
                     {"role": "user", "content": generate.repair_prompt(sql, _feedback(att))}]
    return res
