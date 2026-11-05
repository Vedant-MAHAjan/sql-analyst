# Progress

## Phase 0 — Data and gold audit (done, 2026-11-05)

1. Repo scaffolded; Postgres 16 + `pg_trgm` in Docker Compose on 127.0.0.1:5433; BIRD Mini-Dev (500 questions, 75 tables) loaded into database `bird`.
2. Gold audit ran all 500 PostgreSQL gold queries and compared each with the original SQLite gold: 0 errors, 498 agree ([reports/gold_audit.md](reports/gold_audit.md)).
3. Found a timezone bug in the official PostgreSQL dump (written on a UTC+8 server) that silently breaks 5 gold queries; fixed by setting the `bird` database timezone to `Asia/Shanghai`.
4. Flagged Q788 (gold meaning changed in transpilation) and 89 gold queries that use float4 `REAL`, which exact-match scoring will penalise.
5. Held-out set: 40 new questions with gold SQL on Pagila v3.1.0 (12 simple / 20 moderate / 8 challenging), every answer non-empty, tie-free and frozen in `expected.json`.

## Phase 1 — Evaluator and baseline (done, 2026-11-05)

1. Evaluator scores EX (official set equality), a tolerant EX (numbers to 4 significant digits) and BIRD's Soft-F1; it matches the official `evaluation_ex.py` / `evaluation_f1.py` on every question across 1,500 predictions (500 synthetic, 1,000 real).
2. Found that PostgreSQL parallel aggregation makes float `AVG`/`SUM` differ in the last bit between runs, so exact EX flipped at random; disabling parallel query and synchronized scans makes scoring reproducible.
3. Runner: YAML configs, model calls cached by prompt hash, one JSONL log row per question (SQL, scores, error type, tokens, latency), official-format `predict.json`.
4. Baseline (qwen2.5-coder:14b via Ollama, whole schema, one call): **EX 47.4%** with BIRD hints, **24.2%** without (±4.4 pt 95% CI); simple / moderate / challenging 66.2 / 43.2 / 30.4 with hints.
5. 13.6% of predictions fail to execute, mostly unknown columns (27) and text-vs-bigint comparisons BIRD's schema invites; tolerant EX adds 4.2 points, all from correct answers penalised against float4 golds. p50 latency 3.8 s, $0.
