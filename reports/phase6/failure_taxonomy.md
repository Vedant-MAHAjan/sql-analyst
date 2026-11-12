# Failure taxonomy

50 wrong answers from the final agent run (linked schema + validator + repair,
with BIRD hints; EX 51.8%), sampled in proportion to difficulty (12 simple,
25 moderate, 13 challenging, random seed 42). Each was read against its gold
SQL and the first rows of both results. Per-question labels:
[failure_labels.csv](failure_labels.csv). Labelled by Claude; spot-check
before quoting.

| Category | Count | Share | What it means |
|---|---|---|---|
| Output shape | 8 | 16% | Right data, wrong columns or rows: an extra helper column, an address split in three, names instead of ids |
| **Gold error** | 7 | 14% | The gold SQL does not answer the question (wrong precedence, wrong column, contradicts the hint, arbitrary LIMIT) |
| **Gold ambiguous** | 5 | 10% | The prediction is a valid reading the gold rejects (customers vs rows, owner vs editor) |
| Execution error | 5 | 10% | Still failing after two repairs: MySQL backticks, multi-row scalar subqueries |
| Wrong column | 5 | 10% | A plausible but wrong column: date for consumption, city for county, rank for position |
| Aggregation grain | 3 | 6% | Wrong level: per row instead of per customer, a join that double-counts |
| Wrong join | 3 | 6% | Wrong path or key: `multiverseid` instead of `uuid`, attendance instead of budget |
| Hint misuse | 3 | 6% | Ignored or misapplied the hint (eye vs skin colour, a skipped NOT NULL) |
| Numeric precision | 3 | 6% | Correct, but `numeric` vs the gold's float4; passes tolerant EX |
| Spurious filter | 2 | 4% | Invented a condition (`position = 'Student_Club'`) |
| Date handling | 2 | 4% | `AGE()` vs year subtraction; timestamp vs `DATE()` boundary |
| Value mismatch | 2 | 4% | Literal does not match stored format (`'0:01:54'` vs `'1:54.x'`) |
| NULL ordering | 2 | 4% | PostgreSQL sorts NULLs first on `DESC`; SQLite-derived golds assume last |

## What it says

- **About 30% of "failures" are not model errors**: 24% gold error or ambiguity,
  plus 6% numeric precision that tolerant EX already accepts. On this sample the
  agent's true accuracy is meaningfully above its 51.8% EX, which is why the
  headline stays the official number and these are reported beside it.
- **Output shape is the largest real category (16%).** EX demands the exact
  column set, so a helpful extra column scores zero. A prompt rule ("only the
  columns asked for") is already present and not enough for a 14B model.
- **Schema understanding** (wrong column + wrong join + spurious filter, 20%) is
  the next target; better column descriptions did not help in Phase 2, so this
  points to examples or a stronger generator, not more schema text.
- **Repair's limit is visible**: the five execution errors are exactly the kinds
  Phase 3 could not fix (dialect syntax, query shape).
- **PostgreSQL-specific traps** (NULL ordering, date semantics) cost 8% and come
  from golds transpiled from SQLite.
