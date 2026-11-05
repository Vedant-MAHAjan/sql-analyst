# sql-analyst

A text-to-SQL analyst agent over PostgreSQL, evaluated against ground truth
on BIRD Mini-Dev, with a held-out set on a public non-BIRD database. Models
run locally through Ollama.

Status: **Phase 0 (data and gold audit)**; BIRD part done, held-out set next.

## Setup

```bash
docker compose up -d                 # postgres:16 + pg_trgm on 127.0.0.1:5433
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I data/fetch_minidev.py   # ~800 MB download into data/raw/
./data/load_minidev.sh               # loads 75 tables into database "bird"
.venv/bin/python -m eval.gold_audit  # writes reports/gold_audit.csv
```

## Results so far

- [Gold audit](reports/gold_audit.md): all 500 PostgreSQL gold queries run;
  498 agree with the SQLite originals. Found a timezone bug in the official
  PostgreSQL dump that silently breaks 5 gold queries on a UTC server.
