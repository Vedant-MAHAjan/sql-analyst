"""Tiered linking: a cheap model names the tables a question needs.

Its picks are added to the lexical linker's, so it can only raise recall;
the strong model still writes the SQL.
"""
import json

from agent.schema_index import SchemaIndex

PROMPT_VERSION = "llm-linker-v1"
SYSTEM = (
    "You select the tables a SQL query needs. Given a database's tables with their "
    "columns and a question, list every table needed to answer it, including tables "
    "needed only to join others. Respond with JSON: {\"tables\": [\"...\"]}."
)
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"tables": {"type": "array", "items": {"type": "string"}}},
    "required": ["tables"],
}


def compact_schema(ix: SchemaIndex) -> str:
    return "\n".join(f"{t.name}({', '.join(t.columns)})" for t in ix.tables.values())


def messages(ix: SchemaIndex, question: str, evidence: str | None) -> list[dict]:
    user = f"Tables:\n{compact_schema(ix)}\n\n"
    if evidence:
        user += f"Hint: {evidence}\n\n"
    user += f"Question: {question}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse(text: str, valid: set[str]) -> list[str]:
    try:
        tables = json.loads(text).get("tables") or []
    except (json.JSONDecodeError, AttributeError):
        return []
    out = []
    for t in tables:
        name = str(t).strip().strip('"').lower()
        if name in valid and name not in out:
            out.append(name)
    return out
