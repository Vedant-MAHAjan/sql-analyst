| Config | Set | n | EX | ±95% | EX tol. | Soft-F1 | Exec err. | s/question | tokens/q | vs. reference |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline: whole schema, one call | bird + hints | 500 | 47.4 | 4.4 | 51.6 | 47.0 | 13.6% | 4.1 | 796 | — |
| Schema linking | bird + hints | 500 | 51.0 | 4.4 | 55.6 | 51.1 | 11.8% | 5.6 | 640 | +3.6 (p=0.0133) |
| Agent: linking + validate + repair | bird + hints | 500 | 51.8 | 4.4 | 56.0 | 53.1 | 3.0% | 10.2 | 1,091 | +4.4 (p=0.0128) |
| Agent on 7B model | bird + hints | 500 | 45.0 | 4.4 | 46.4 | 46.6 | 10.4% | 4.8 | 1,213 | -6.8 (p=0.0011) |
| Agent + planner + critic (200-question sample) | bird + hints | 200 | 42.5 | 6.9 | 45.5 | 44.5 | 5.0% | 37.1 | 2,827 | -6.0 (p=0.0501) |
| Baseline: whole schema, one call | bird | 500 | 24.2 | 3.8 | 26.0 | 25.0 | 11.4% | 3.4 | 759 | — |
| Schema linking | bird | 500 | 31.2 | 4.1 | 33.2 | 31.1 | 14.2% | 3.9 | 557 | +7.0 (p=0.0001) |
| Agent: linking + validate + repair | bird | 500 | 31.6 | 4.1 | 33.0 | 31.6 | 10.6% | 21.7 | 978 | +7.4 (p=0.0002) |
| Agent + 7B table picker (tiered) | bird | 500 | 34.2 | 4.2 | 36.0 | 34.3 | 5.8% | 20.3 | 1,009 | +2.6 (p=0.0044) |
| Held-out: baseline | heldout + hints | 40 | 90.0 | 9.3 | 90.0 | 87.6 | 2.5% | 3.2 | 1,020 | — |
| Held-out: agent | heldout + hints | 40 | 95.0 | 6.8 | 95.0 | 91.6 | 0.0% | 8.5 | 727 | +5.0 (p=0.688) |
