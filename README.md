# sql-analyst

A text-to-SQL analyst agent over PostgreSQL, evaluated against ground truth
on BIRD Mini-Dev, with a held-out set on a public non-BIRD database. Models
run locally through Ollama.

Status: **Phases 0–5 done** (see [progress.md](progress.md)). Phase 6
(experiments and write-up) next.

## Setup

```bash
docker compose up -d                 # postgres:16 + pg_trgm on 127.0.0.1:5433
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I data/fetch_minidev.py   # ~800 MB download into data/raw/
./data/load_minidev.sh               # loads 75 tables into database "bird"
.venv/bin/python -m eval.gold_audit  # writes reports/gold_audit.csv
./data/load_pagila.sh                # held-out database "pagila" (v3.1.0)
.venv/bin/python -m eval.heldout_check      # 40 held-out golds vs frozen results
ollama pull qwen2.5-coder:14b
.venv/bin/python -m eval.runner eval/configs/baseline.yaml   # writes runs/<id>/
python3.11 -m venv .venv-official && .venv-official/bin/pip install psycopg2-binary func_timeout PyMySQL
.venv/bin/python -m eval.official_check runs/<id>   # re-score with BIRD's own scripts
```

## Baseline (Phase 1)

BIRD Mini-Dev, PostgreSQL, 500 questions; qwen2.5-coder:14b on Ollama,
whole schema in the prompt, one call. EX is scored exactly as BIRD scores it
(confirmed identical to the official scripts per question); ±4.4 points 95% CI.

| Config | EX | EX (tolerant) | Soft-F1 | Exec errors | p50 latency |
|---|---|---|---|---|---|
| With BIRD hints | 47.4 | 51.6 | 47.0 | 13.6% | 3.8 s |
| Without hints | 24.2 | 26.0 | 25.0 | 11.4% | 3.0 s |

For reference, BIRD's published Mini-Dev PostgreSQL baselines are 35.8 (GPT-4)
and 36.0 (GPT-4 Turbo), with hints. Summaries: [reports/phase1](reports/phase1).

## Schema linking (Phase 2)

Table-level linking (up to 5 tables plus join-path bridges) with trigram
value matches noted beside their columns. Schema recall: share of questions
whose gold SQL columns are all in the linked schema.

| Config | Schema recall | Prompt size vs whole | EX | Paired vs baseline |
|---|---|---|---|---|
| Linked, with hints | 96.4% | 0.72× | 51.0 (+3.6) | p = 0.013 |
| Linked + BIRD descriptions, with hints | 96.4% | 2.05× | 50.8 (+3.4) | p = 0.06 |
| Linked, without hints | 76.6% | — | 31.2 (+7.0) | p < 0.001 |

```bash
.venv/bin/python -m agent.value_index build        # once, ~30 s
.venv/bin/python -m eval.schema_recall             # recall + prompt size
.venv/bin/python -m eval.runner eval/configs/linked_evidence.yaml
```

Summaries: [reports/phase2](reports/phase2).

## Validate, execute, repair (Phase 3)

Model SQL is checked by a sqlglot validator and run as the read-only
`analyst_ro` role; on a database error the error, position and hint go back
to the model, at most twice. With hints, linked schema:

| | EX | Execution errors |
|---|---|---|
| First attempt | 49.8 | 11.6% |
| After repair (max 2) | **51.8** | **3.0%** |

Repair fixed 10 questions and broke none (p = 0.002), but most repaired
queries run without becoming correct (43 of 58 run, 10 correct). Summary:
[reports/phase3](reports/phase3).

## Using it (Phase 4)

```bash
.venv/bin/uvicorn serve.api:app --port 8008      # web page at http://localhost:8008
.venv/bin/python serve/mcp_server.py              # MCP server (stdio)
claude mcp add sql-analyst -- "$PWD/.venv/bin/python" "$PWD/serve/mcp_server.py"
```

The page shows the answer, a chart picked from the result's shape, the rows,
and the SQL with the model's assumptions and any repair attempts. The MCP
server exposes `list_databases`, `describe_schema` and `ask`. Results are
capped at 1,000 rows at fetch time (no `LIMIT` is injected), and at most 50
rows ever go back to the model.

## Guardrails (Phase 5)

Safety comes from the database and the validator; the prompt is defense in
depth. 57 attacks run against clone databases with planted prompt injections,
scored by database state, not by reading replies.

| Layers on | Writes | Exfiltration | Resource | Injection |
|---|---|---|---|---|
| All | 0% | 0% | 0% | 0% |
| No prompt guard | 0% | 0% | 0% | 0% |
| Database role only | 0% | 13.3% | 0% | 17.6% |

```bash
./data/setup_attack_dbs.sh                         # clones + planted injections
.venv/bin/python -m eval.attack_suite full         # or no_prompt, role_only
```

Details, per-layer attribution and costs: [reports/phase5](reports/phase5).

## Held-out set

[`data/heldout/questions.jsonl`](data/heldout/questions.jsonl): 40 questions
(12 simple, 20 moderate, 8 challenging) with gold SQL on
[Pagila](https://github.com/devrimgunduz/pagila) v3.1.0, a public PostgreSQL
sample database that is not part of BIRD. Edit
[`build_questions.py`](data/heldout/build_questions.py), not the JSONL.
The questions are new; the schema is widely known (Pagila is a port of MySQL's
Sakila), so this is a contamination check on the questions, not on the schema.
Prompts are frozen before the held-out run, and nothing is tuned on it.

## Results so far

- [Gold audit](reports/gold_audit.md): all 500 PostgreSQL gold queries run;
  498 agree with the SQLite originals. Found a timezone bug in the official
  PostgreSQL dump that silently breaks 5 gold queries on a UTC server.
