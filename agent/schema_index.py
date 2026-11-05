"""Per-database schema index: columns, keys, and BIRD's column descriptions."""
import csv
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from agent.schema import ROOT, _quote_fn, tables_for

DESC_ROOT = ROOT / "data/raw/minidev/minidev/MINIDEV/dev_databases"


@dataclass
class Column:
    name: str
    type: str
    description: str = ""
    values: str = ""  # BIRD value_description


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    table: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class SchemaIndex:
    db_id: str
    tables: dict[str, Table]
    foreign_keys: list[ForeignKey]
    quote: object
    # Set after construction; used for join paths only, never rendered.
    inferred_joins: list[ForeignKey] = field(default_factory=list)

    def render(self, selection: dict[str, list[str] | None],
               value_hits: dict[tuple[str, str], list[str]] | None = None,
               describe: bool = True) -> str:
        """CREATE TABLE text for the selected tables (None = all columns)."""
        q, value_hits = self.quote, value_hits or {}
        blocks = []
        for tname in self.tables:
            if tname not in selection:
                continue
            table, wanted = self.tables[tname], selection[tname]
            lines = []
            for col in table.columns.values():
                if wanted is not None and col.name not in wanted:
                    continue
                notes = []
                if describe and col.description and _informative(col):
                    notes.append(col.description)
                if describe and col.values:
                    notes.append(col.values)
                hits = value_hits.get((tname, col.name))
                if hits:
                    notes.append("matching values: " + ", ".join(repr(v) for v in hits))
                note = " -- " + "; ".join(_short(n) for n in notes) if notes else ""
                lines.append((f"  {q(col.name)} {col.type}", note))
            if table.primary_key:
                lines.append((f"  PRIMARY KEY ({', '.join(q(c) for c in table.primary_key)})", ""))
            for fk in self.foreign_keys:
                if fk.table == tname and fk.ref_table in selection:
                    lines.append((
                        f"  FOREIGN KEY ({', '.join(q(c) for c in fk.columns)}) "
                        f"REFERENCES {q(fk.ref_table)} ({', '.join(q(c) for c in fk.ref_columns)})", ""))
            # Comma goes before the comment so the DDL stays valid SQL.
            blocks.append(f"CREATE TABLE {q(tname)} (\n" + "\n".join(
                f"{text}{',' if i < len(lines) - 1 else ''}{note}"
                for i, (text, note) in enumerate(lines)) + "\n);")
        return "\n\n".join(blocks)


def _informative(col: Column) -> bool:
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    return norm(col.description) != norm(col.name)


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _read_descriptions(db_id: str, table: str) -> dict[str, tuple[str, str]]:
    folder = DESC_ROOT / db_id / "database_description"
    path = next((p for p in folder.glob("*.csv") if p.stem.lower() == table), None) \
        if folder.exists() else None
    if path is None:
        return {}
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = {}
    for row in csv.DictReader(text.splitlines()):
        name = (row.get("original_column_name") or "").strip()
        if not name:
            continue
        desc = (row.get("column_description") or row.get("column_name") or "").strip()
        out[name.lower()] = (desc, (row.get("value_description") or "").strip())
    return out


_CACHE: dict[tuple[str, str], SchemaIndex] = {}


def build(conn: psycopg.Connection, db_id: str) -> SchemaIndex:
    key = (conn.info.dbname, db_id)
    if key not in _CACHE:
        _CACHE[key] = _build(conn, db_id)
    return _CACHE[key]


def _build(conn: psycopg.Connection, db_id: str) -> SchemaIndex:
    names = tables_for(conn, db_id)
    tables = {t: Table(t) for t in names}
    for t, c, typ in conn.execute(
        "SELECT table_name, column_name, "
        "CASE WHEN data_type = 'USER-DEFINED' THEN udt_name "
        "WHEN data_type = 'ARRAY' THEN substr(udt_name, 2) || '[]' ELSE data_type END "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = ANY(%s) ORDER BY table_name, ordinal_position", (names,)
    ):
        tables[t].columns[c] = Column(c, typ)
    fks = []
    for t, kind, cols, ft, fcols in conn.execute(
        "SELECT rel.relname, con.contype, "
        "(SELECT array_agg(a.attname ORDER BY k.n) FROM unnest(con.conkey) "
        " WITH ORDINALITY k(attnum, n) JOIN pg_attribute a "
        " ON a.attrelid = con.conrelid AND a.attnum = k.attnum), frel.relname, "
        "(SELECT array_agg(a.attname ORDER BY k.n) FROM unnest(con.confkey) "
        " WITH ORDINALITY k(attnum, n) JOIN pg_attribute a "
        " ON a.attrelid = con.confrelid AND a.attnum = k.attnum) "
        "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
        "LEFT JOIN pg_class frel ON frel.oid = con.confrelid "
        "JOIN pg_namespace n ON n.oid = rel.relnamespace "
        "WHERE n.nspname = 'public' AND con.contype IN ('p', 'f') "
        "AND rel.relname = ANY(%s) ORDER BY con.conname", (names,)
    ):
        if kind == "p":
            tables[t].primary_key = list(cols)
        elif ft in tables:
            fks.append(ForeignKey(t, list(cols), ft, list(fcols)))
    for t in tables.values():
        descs = _read_descriptions(db_id, t.name)
        for col in t.columns.values():
            desc, values = descs.get(col.name.lower(), ("", ""))
            col.description, col.values = desc, values
    ix = SchemaIndex(db_id, tables, fks, _quote_fn(conn))
    ix.inferred_joins = _infer_joins(tables, fks)
    return ix


def _infer_joins(tables: dict[str, Table], fks: list[ForeignKey]) -> list[ForeignKey]:
    """Undeclared joins: a column named like another table's one-column primary key."""
    declared = {(fk.table, tuple(fk.columns)) for fk in fks}
    pk_owner = {}
    for t in tables.values():
        if len(t.primary_key) == 1 and t.primary_key[0].lower().endswith("id"):
            pk_owner.setdefault(t.primary_key[0].lower(), t.name)
    out = []
    for t in tables.values():
        for col in t.columns:
            owner = pk_owner.get(col.lower())
            if owner and owner != t.name and (t.name, (col,)) not in declared:
                out.append(ForeignKey(t.name, [col], owner, tables[owner].primary_key))
    return out
