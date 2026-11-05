"""Phase 1 baseline: whole schema in the prompt, one call, no repair."""
import json
import re

PROMPT_VERSION = "baseline-v1"

SYSTEM = (
    "You are an expert PostgreSQL analyst. Given a database schema and a "
    "question, write one PostgreSQL SELECT query that answers it. Select only "
    "the columns the question asks for. Respond with JSON: {\"sql\": \"...\"}."
)
SQL_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}


def build_prompt(schema_ddl: str, question: str, evidence: str | None) -> str:
    parts = [f"Database schema:\n{schema_ddl}"]
    if evidence:
        parts.append(f"Hint: {evidence}")
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)


def parse_sql(text: str) -> str:
    try:
        sql = json.loads(text)["sql"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S)
        sql = fence.group(1) if fence else text
    return sql.strip().rstrip(";").strip()
