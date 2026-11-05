# sql-analyst

A text-to-SQL analyst agent over PostgreSQL, evaluated against ground truth
on BIRD Mini-Dev, with a held-out set on a public non-BIRD database. Models
run locally through Ollama.

Status: **Phase 0 (data and gold audit) done.** Phase 1 (evaluator and
baseline) next.

## Setup

```bash
docker compose up -d                 # postgres:16 + pg_trgm on 127.0.0.1:5433
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I data/fetch_minidev.py   # ~800 MB download into data/raw/
./data/load_minidev.sh               # loads 75 tables into database "bird"
.venv/bin/python -m eval.gold_audit  # writes reports/gold_audit.csv
./data/load_pagila.sh                # held-out database "pagila" (v3.1.0)
.venv/bin/python -m eval.heldout_check      # 40 held-out golds vs frozen results
```

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
