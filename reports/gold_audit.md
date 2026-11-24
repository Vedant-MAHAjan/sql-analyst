# Gold audit — BIRD Mini-Dev (PostgreSQL)

Produced by `python -m eval.gold_audit`; per-question rows are in
[`gold_audit.csv`](gold_audit.csv). Every PostgreSQL gold query is executed
against the Mini-Dev PostgreSQL dump and compared with the original SQLite
gold query on the SQLite copy of the same database (numbers rounded to 5
significant digits, dates compared as ISO text).

## Result

| Check | Count |
|---|---|
| PostgreSQL gold queries executed | 500 |
| Errors / timeouts / empty results | 0 / 0 / 0 |
| Agree with SQLite gold | 498 (2 of them only with a 600 s SQLite timeout: 518, 701) |
| Disagree with SQLite gold | 2 |

## Findings

**1. Dump timezone (fixed in setup).** The 11 `timestamptz` columns in
`codebase_community` (badges, comments, posthistory, postlinks, posts, users)
were dumped from a UTC+8 server. Under a UTC session they read 8 hours earlier
than the SQLite originals, so 5 gold queries returned wrong results
(532, 533, 683: year/date boundaries shift; 563, 565: exact-timestamp
filters return nothing). `docker/initdb/01_databases.sql` sets
`ALTER DATABASE bird SET timezone = 'Asia/Shanghai'`, after which all 5 match.
Anyone loading this dump into a UTC server silently gets those 5 wrong.

**2. Question 788: gold meaning changed in transpilation.**
*"How many percent of female heroes were published by Marvel Comics?"*
The PostgreSQL gold computes Marvel ÷ female heroes (54.95%); the SQLite gold
computes female ÷ Marvel heroes (28.68%). The PostgreSQL version matches the
question's wording. Kept as is; noted because SQLite-trained predictions will
be scored wrong here.

**3. Question 1482: float4 precision.** The PostgreSQL gold uses
`CAST(... AS REAL)`, which is 4-byte float in PostgreSQL (8-byte in SQLite),
so results differ in the 4th–5th significant digit (545.41 vs 545.40).

**4. Scoring risk for Phase 1.** 89 of the 500 PostgreSQL gold queries use
`CAST(... AS REAL)`. BIRD's EX is exact set equality, so a mathematically
correct prediction that computes in `double precision` or `numeric` will be
scored wrong against a float4 gold. The evaluator will report official
(exact) EX as the headline and a numeric-tolerant EX beside it, with the
number of questions where the two differ.

**5. Duplicate questions.** Question IDs 137 and 138 (financial) each appear twice,
with identical question, hint and gold SQL, so Mini-Dev has 498 distinct questions in
500 rows. Scores keep all 500 rows, as the official scripts do; paired tests key rows by
(question_id, occurrence) so neither copy is dropped.

## Prior reports

Checked against the upstream tracker before publishing. The timezone offset was
reported in [#18](https://github.com/bird-bench/mini_dev/issues/18) (maintainers confirmed the HKT setup), float nondeterminism
in [#48](https://github.com/bird-bench/mini_dev/issues/48) (which also identifies `work_mem`; setup now pins it), and the
duplicate questions in [#17](https://github.com/bird-bench/mini_dev/issues/17). These are not claimed as new findings.
