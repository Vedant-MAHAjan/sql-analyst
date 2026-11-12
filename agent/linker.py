"""Schema linking: pick the tables and columns a question needs.

Scores every column by lexical overlap with the question and hint (column
name, BIRD description), explicit mentions in the hint, and value-index
hits; keeps the best tables, then adds bridge tables on foreign-key paths so
the selected tables can be joined.
"""
import re
from collections import deque
from dataclasses import dataclass, field

import psycopg

from agent import schema_index, value_index

STOP = value_index.STOPWORDS | {"refer", "refers", "mean", "means", "id", "value"}


def _stem(w: str) -> str:
    for suf in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str) -> set[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w.endswith("id") and len(w) > 4:  # driverid -> driver
            w = w[:-2]
        if w not in STOP and (len(w) > 1 or w.isdigit()):
            out.add(_stem(w))
    return out


@dataclass
class Link:
    selection: dict[str, list[str] | None]
    value_hits: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    table_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class LinkerConfig:
    min_table_score: float = 0.3
    max_tables: int = 5
    mode: str = "table"         # "table": all columns of kept tables; "column": pruned
    min_column_score: float = 0.3
    extra_columns: int = 3       # column mode: best non-matching columns kept per table


def column_scores(ix: schema_index.SchemaIndex, question: str, evidence: str,
                  hits: list) -> dict[tuple[str, str], float]:
    q = tokens(question) | tokens(evidence)
    ev = evidence.lower()
    hit_cols = {}
    for t, c, _v, sim in hits:
        hit_cols[(t, c)] = max(hit_cols.get((t, c), 0), sim)
    scores = {}
    for t in ix.tables.values():
        for col in t.columns.values():
            name = tokens(col.name)
            s = len(q & name) / len(name) if name else 0.0
            desc = tokens(col.description)
            if desc:
                s += 0.3 * min(len(q & desc), 3) / min(len(desc), 3)
            if ev and re.search(r"(?<![\w])" + re.escape(col.name.lower()) + r"(?![\w])", ev):
                s += 2.0
            if (t.name, col.name) in hit_cols:
                s += 1.0 + hit_cols[(t.name, col.name)]
            scores[(t.name, col.name)] = s
    return scores


def _fk_graph(ix: schema_index.SchemaIndex) -> dict[str, set[str]]:
    g: dict[str, set[str]] = {t: set() for t in ix.tables}
    for fk in ix.foreign_keys + ix.inferred_joins:
        g[fk.table].add(fk.ref_table)
        g[fk.ref_table].add(fk.table)
    return g


def _bridge(graph: dict[str, set[str]], keep: list[str]) -> set[str]:
    """Tables on shortest FK paths connecting the kept tables to the first one."""
    out = set(keep)
    root = keep[0]
    for target in keep[1:]:
        prev, seen, queue = {}, {root}, deque([root])
        while queue:
            node = queue.popleft()
            if node == target:
                break
            for nxt in sorted(graph[node]):
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = node
                    queue.append(nxt)
        node = target
        while node in prev:
            node = prev[node]
            out.add(node)
    return out


def link(conn: psycopg.Connection, db_id: str, question: str, evidence: str = "",
         cfg: LinkerConfig | None = None, extra_tables: list[str] | None = None) -> Link:
    cfg = cfg or LinkerConfig()
    ix = schema_index.build(conn, db_id)
    hits = value_index.lookup(conn, db_id, f"{question} {evidence}")
    scores = column_scores(ix, question, evidence, hits)
    q = tokens(question) | tokens(evidence)
    table_scores = {}
    for t in ix.tables.values():
        col_s = sorted((scores[(t.name, c)] for c in t.columns), reverse=True)
        name = tokens(t.name)
        name_s = len(q & name) / len(name) if name else 0.0
        table_scores[t.name] = name_s + (col_s[0] if col_s else 0) + 0.2 * sum(col_s[1:3])
    ranked = sorted(table_scores, key=table_scores.get, reverse=True)
    keep = [t for t in ranked if table_scores[t] >= cfg.min_table_score][: cfg.max_tables]
    if not keep:
        keep = ranked[:1]
    # Tables named by a cheaper model (tiered linking) are added, never removed.
    keep += [t for t in extra_tables or [] if t in ix.tables and t not in keep]
    tables = _bridge(_fk_graph(ix), keep)

    schema_words = set()
    for t in ix.tables.values():
        schema_words |= tokens(t.name)
        for c in t.columns:
            schema_words |= tokens(c)
    value_hits: dict[tuple[str, str], list[str]] = {}
    for t, c, v, _sim in hits:
        # "drivers" in a question names the table, not the value 'driver'.
        if t in tables and not tokens(v) <= schema_words:
            value_hits.setdefault((t, c), []).append(v)

    selection: dict[str, list[str] | None] = {}
    for t in tables:
        if cfg.mode == "table":
            selection[t] = None
            continue
        table = ix.tables[t]
        cols = set(table.primary_key)
        for fk in ix.foreign_keys + ix.inferred_joins:
            if fk.table == t and fk.ref_table in tables:
                cols.update(fk.columns)
            if fk.ref_table == t and fk.table in tables:
                cols.update(fk.ref_columns)
        ranked_cols = sorted(table.columns, key=lambda c: scores[(t, c)], reverse=True)
        cols.update(c for c in ranked_cols if scores[(t, c)] >= cfg.min_column_score)
        cols.update(ranked_cols[: cfg.extra_columns])
        selection[t] = [c for c in table.columns if c in cols]
    return Link(selection, value_hits, table_scores)
