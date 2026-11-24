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
3. Schema recall (sqlglot-resolved gold columns all present): **96.4%** with hints at 72% of the whole-schema prompt size (target ≥95%); 84.0% without hints (an earlier draft said 76.6%, from a stricter sweep setting); column-level pruning fell to 83–87%, so linking stays table-level.
4. EX with hints rose 47.4 → **51.0** (McNemar p = 0.013); without hints 24.2 → **31.2** (p < 0.001), driven by matched values such as 'Bahrain Grand Prix' → `races.name`.
5. BIRD column descriptions did not help (50.8, p = 0.06 vs baseline) and doubled the prompt, so they are off by default; remaining errors are mostly SQLite functions and text-vs-number comparisons, which Phase 3 targets.

## Phase 3 — Generate, validate, execute, repair (done, 2026-11-05)

1. Model SQL now runs as a read-only `analyst_ro` role (SELECT only, read-only transactions, 30 s timeout, no access to the `retrieval` schema); writes and temp tables are refused by the database itself.
2. sqlglot validator (one statement, SELECT/WITH only, tables on the database's allowlist, denylist incl. `pg_sleep`, `set_config`, `query_to_xml`) passes all 540 gold queries and blocks every write and escape attempt tried, including a `DELETE` hidden in a CTE.
3. Structured output (SQL, assumptions, abstain) plus a repair loop that feeds PostgreSQL's error, position and hint back at most twice: execution-error rate **11.6% → 3.0%**, EX **49.8 → 51.8** (repair fixed 10, broke 0; p = 0.002).
4. Repair makes 43 of 58 failing queries run but only 10 correct: unknown columns 13 run / 4 correct, grouping errors 9 / 2, SQLite functions 8 / 2; it cannot fix MySQL-style backticks, because sqlglot's parse message is less useful than PostgreSQL's.
5. Net vs Phase 2 linking is +0.8 EX (not significant, p = 0.77): the structured-output prompt costs ~1 point on the first attempt and triples output tokens (p50 latency 4.8 → 7.9 s); vs the Phase 1 baseline it is +4.4 (p = 0.017).

## Phase 4 — Answer layer and interfaces (done, 2026-11-11)

1. Answer layer: a one-or-two-sentence summary from at most 50 result rows (delimited as data, not instructions) and a chart picked by result shape: one value → number, time + measure → line (year + month combined), category or id + measure → bar.
2. Serving execution uses a server-side cursor capped at 1,000 rows at fetch time, so PostgreSQL stops early and the SQL is never rewritten with a `LIMIT`; model SQL still runs as `analyst_ro` behind the validator and repair loop.
3. FastAPI (`/api/databases`, `/api/schema/{db}`, `/api/ask`) plus a no-build React + Vega-Lite page showing the answer, chart, rows, SQL, assumptions, repair history, tables given to the model and timings; works at phone width.
4. MCP server (stdio) with `list_databases`, `describe_schema` and `ask`, tested end to end with the MCP Python client.
5. Done-when met on Pagila: "How many rentals were made each month?" → SQL, 5 rows, line chart in ~14 s; "revenue per store" → bar chart; evaluation results unchanged (cached Phase 3 sample replays identically).

## Phase 5 — Guardrails and attack suite (done, 2026-11-11)

1. 57 attacks (15 writes, 15 exfiltration, 10 resource, 17 planted injections) run on clone databases and scored by state: data/catalog fingerprints, canary secrets, wall time + health check, and an injected marker the answer obeyed rather than quoted.
2. With all layers on, attack success is **0%** in every category, no data changed, and utility under attack is 94.1%; with only the database role, writes still fail (0%) but catalog reads (13.3%) and injections (17.6%) get through.
3. Each layer was measured alone: the validator blocked every write and catalog read when the prompt guard was off; the role blocked every write that reached it; column grants kept `staff.password` out of both the prompt and the value index.
4. Found and fixed: the value index stored password hashes; a model-issued `BEGIN` could leave connections aborted; the summary prompt's "data, not instructions" line did not stop injections (17.6% success), so a grounding check now replaces any summary that states no value from the result — injection success 0%.
5. The prompt guard costs nothing measurable on BIRD (51.0 vs 49.0 EX on 100 questions, p = 0.69); the grounding fallback replaces about 1 in 10 ordinary answers with a plain readout; huge result cells are cut to 200 characters before summarising (R10: 127 s → 23 s).

## Phase 6 — Experiments and write-up (done, 2026-11-11)

1. Ablations, all paired against their reference: the 7B model loses 6.8 EX (p = 0.001) for 2.3× speed; planner + critic loses 6.0 (p = 0.05, 200-question sample) at 4× the time; a 7B table picker added to linking raises no-hint recall 84.0% → 95.8% and EX +2.6 (p = 0.004).
2. Reliability: on 100 questions at temperature 0.7, pass@1 51%, **pass^4 34%**, pass@4 66% — a third of questions flip between runs. Held-out (prompts frozen by hash first): agent 95.0% vs baseline 90.0% on 40 Pagila questions, higher than BIRD, so not a memorization signal either way.
3. Failure taxonomy of 50 failures: 14% gold errors + 10% ambiguous golds + 6% numeric precision are not model errors; output shape (16%) and schema misreads (20%) are the real ones. Also found two duplicate questions in Mini-Dev and a validator crash on sqlglot `TokenError` (fixed).
4. Run reports (HTML, tradeoff chart, run diffs), a 60-question CI smoke gate with a self-hosted-runner workflow, and `make reproduce`, which rebuilds the results table exactly from a committed 1.5 MB model-call cache without a GPU.
5. Final README with results, findings, safety table, reproduction and limitations.

## Launch prep correction (2026-11-23)

Upstream already reports the timezone offset ([#18](https://github.com/bird-bench/mini_dev/issues/18)), float nondeterminism ([#48](https://github.com/bird-bench/mini_dev/issues/48)) and duplicate questions ([#17](https://github.com/bird-bench/mini_dev/issues/17)). Earlier blocks describe what this project hit; they are not new discoveries.
