"""Phase 3 generation: structured output (SQL, assumptions, abstain) and repair prompts."""
import json
import re

PROMPT_VERSION = "agent-v1"

SYSTEM = """You are an expert PostgreSQL analyst. Given a database schema and a question, \
write one PostgreSQL query (SELECT or WITH) that answers it.
- Select only the columns the question asks for, in the order it asks for them.
- Use PostgreSQL syntax and functions only. Hints may be written in SQLite syntax: \
translate them (CASE instead of IIF, EXTRACT or TO_CHAR instead of STRFTIME, \
SUBSTRING instead of SUBSTR on non-text).
- Many numeric-looking columns are stored as text; cast explicitly when comparing \
them with numbers or doing arithmetic.
- "matching values" in a column comment are exact values stored in that column.
Respond with JSON: {"sql": "...", "assumptions": ["..."], "abstain": false}. \
Set "abstain" to true, with an empty "sql", only if the schema cannot answer the question."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "abstain": {"type": "boolean"},
    },
    "required": ["sql", "assumptions", "abstain"],
}


def build_prompt(schema_ddl: str, question: str, evidence: str | None) -> str:
    parts = [f"Database schema:\n{schema_ddl}"]
    if evidence:
        parts.append(f"Hint: {evidence}")
    parts.append(f"Question: {question}")
    return "\n\n".join(parts)


def parse(text: str) -> dict:
    try:
        out = json.loads(text)
        if not isinstance(out, dict):
            raise TypeError
    except (json.JSONDecodeError, TypeError):
        fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S)
        out = {"sql": fence.group(1) if fence else text}
    sql = str(out.get("sql") or "").strip().rstrip(";").strip()
    return {
        "sql": sql,
        "assumptions": [str(a) for a in out.get("assumptions") or []][:5],
        "abstain": bool(out.get("abstain")) and not sql,
    }


def error_context(sql: str, message: str, hint: str = "", position: int = 0) -> str:
    text = f"Error: {message}"
    if position:
        start = max(position - 40, 0)
        text += f"\nNear: ...{sql[start:position + 40]}..."
    if hint:
        text += f"\nHint from PostgreSQL: {hint}"
    return text


def repair_prompt(sql: str, error: str) -> str:
    return (f"That query failed.\n\nQuery:\n{sql}\n\n{error}\n\n"
            "Write a corrected query that answers the original question. "
            "Respond with the same JSON format.")
