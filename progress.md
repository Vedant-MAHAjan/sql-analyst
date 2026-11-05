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

## Phase 2 — Schema linking and value retrieval (done, 2026-11-05)

1. Schema index (catalog + inferred joins for databases with no declared foreign keys + BIRD column descriptions) and a `pg_trgm` value index of 406,578 distinct values in a hidden `retrieval` schema; lookups take 10–40 ms.
2. Linker scores columns by name/description overlap, hint mentions and value hits, keeps up to 5 tables, and adds bridge tables on join paths; a fix for Python hash-seed order made it deterministic.
3. Schema recall (sqlglot-resolved gold columns all present): **96.4%** with hints at 72% of the whole-schema prompt size (target ≥95%); 76.6% without hints; column-level pruning fell to 83–87%, so linking stays table-level.
4. EX with hints rose 47.4 → **51.0** (McNemar p = 0.013); without hints 24.2 → **31.2** (p < 0.001), driven by matched values such as 'Bahrain Grand Prix' → `races.name`.
5. BIRD column descriptions did not help (50.8, p = 0.06 vs baseline) and doubled the prompt, so they are off by default; remaining errors are mostly SQLite functions and text-vs-number comparisons, which Phase 3 targets.

## Phase 3 — Generate, validate, execute, repair (done, 2026-11-05)

1. Model SQL now runs as a read-only `analyst_ro` role (SELECT only, read-only transactions, 30 s timeout, no access to the `retrieval` schema); writes and temp tables are refused by the database itself.
2. sqlglot validator (one statement, SELECT/WITH only, tables on the database's allowlist, denylist incl. `pg_sleep`, `set_config`, `query_to_xml`) passes all 540 gold queries and blocks every write and escape attempt tried, including a `DELETE` hidden in a CTE.
3. Structured output (SQL, assumptions, abstain) plus a repair loop that feeds PostgreSQL's error, position and hint back at most twice: execution-error rate **11.6% → 3.0%**, EX **49.8 → 51.8** (repair fixed 10, broke 0; p = 0.002).
4. Repair makes 43 of 58 failing queries run but only 10 correct: unknown columns 13 run / 4 correct, grouping errors 9 / 2, SQLite functions 8 / 2; it cannot fix MySQL-style backticks, because sqlglot's parse message is less useful than PostgreSQL's.
5. Net vs Phase 2 linking is +0.8 EX (not significant, p = 0.77): the structured-output prompt costs ~1 point on the first attempt and triples output tokens (p50 latency 4.8 → 7.9 s); vs the Phase 1 baseline it is +4.4 (p = 0.017).
