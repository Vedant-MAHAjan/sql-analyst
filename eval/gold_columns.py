"""Which (table, column) pairs does a SQL query reference? Used for schema recall."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope


def schema_map(conn, tables: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {t: {} for t in tables}
    for t, c, typ in conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)", (tables,)
    ):
        out[t][c] = typ
    return out


def referenced_columns(sql: str, schema: dict[str, dict[str, str]]) -> set[tuple[str, str]]:
    tree = sqlglot.parse_one(sql, read="postgres")
    tree = qualify(tree, schema=schema, dialect="postgres",
                   validate_qualify_columns=False, identify=False)
    cols: set[tuple[str, str]] = set()
    for scope in traverse_scope(tree):
        for col in scope.columns:
            source = scope.sources.get(col.table)
            if isinstance(source, exp.Table) and source.name in schema:
                if col.name in schema[source.name]:
                    cols.add((source.name, col.name))
        # COUNT(*) etc. still needs the table even with no named column.
        for source in scope.sources.values():
            if isinstance(source, exp.Table) and source.name in schema:
                cols.add((source.name, "*"))
    return cols
