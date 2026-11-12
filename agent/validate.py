"""Check model SQL before it reaches the database.

One statement, read-only query only, tables on the allowlist, no dangerous
functions. The database role is the real guardrail; this rejects bad SQL
early with a message the repair loop can act on.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

DENIED_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "pg_read_file",
    "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "dblink", "dblink_exec",
    "dblink_connect", "lo_import", "lo_export", "lo_get", "lo_open", "set_config",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "query_to_xml", "query_to_xml_and_xmlschema", "table_to_xml",
    "pg_logical_emit_message", "pg_advisory_lock", "pg_advisory_xact_lock",
}
_WRITE_NODES = tuple(getattr(exp, n) for n in (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable",
    "Command", "Copy", "Set", "Transaction", "Commit", "Rollback", "Into", "Lock",
    "Grant", "TruncateTable", "Use",
) if hasattr(exp, n))


@dataclass
class Validation:
    ok: bool
    error_type: str = ""
    message: str = ""


def _fail(kind: str, msg: str) -> Validation:
    return Validation(False, kind, msg)


def validate(sql: str, allowed_tables: set[str]) -> Validation:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as exc:  # incl. TokenError
        first = str(exc).splitlines()[0]
        return _fail("parse_error", f"could not parse as PostgreSQL: {first}")
    if len(statements) != 1:
        return _fail("multiple_statements",
                     f"expected exactly one statement, got {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        return _fail("not_select", f"only SELECT/WITH queries are allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, _WRITE_NODES):
            return _fail("not_select", f"{node.key.upper()} is not allowed in a read-only query")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in DENIED_FUNCTIONS:
                return _fail("denied_function", f"function {name}() is not allowed")
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables}
    for table in tree.find_all(exp.Table):
        if not table.name:  # table function, e.g. generate_series(...)
            continue
        schema = table.db.lower()
        name = table.name.lower()
        if schema and schema != "public":
            return _fail("unknown_table", f"table {schema}.{name} is not available")
        if name not in allowed and name not in cte_names:
            return _fail("unknown_table", f'relation "{name}" does not exist in this database')
    return Validation(True)
