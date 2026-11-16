# LLM judge vs deterministic scorer

Judge: Claude `sonnet` through `claude -p` (no tools). Replies from: `20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl`, `20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl`. The judge prompts are in `src/courts_analyst/evaluation/llm_judge.py`.

## Agreement on the agent's real replies

| Judge | Replies | Agree | Cohen's κ | Scorer pass, judge fail | Scorer fail, judge pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| generic | 486 | 96.7% | 0.86 | 4 | 12 |
| informed | 486 | 97.1% | 0.88 | 5 | 9 |

### By split

| Judge | Split | Replies | Agree | κ |
| --- | --- | ---: | ---: | ---: |
| generic | dev | 351 | 97.2% | 0.86 |
| generic | test2 | 135 | 95.6% | 0.85 |
| informed | dev | 351 | 97.2% | 0.86 |
| informed | test2 | 135 | 97.0% | 0.90 |

### By suite

| Judge | Suite | Replies | Agree | Scorer pass, judge fail | Scorer fail, judge pass |
| --- | --- | ---: | ---: | ---: | ---: |
| generic | adversarial | 162 | 95.7% | 0 | 7 |
| generic | e2e | 156 | 99.4% | 1 | 0 |
| generic | engine | 63 | 98.4% | 1 | 0 |
| generic | explanation | 60 | 96.7% | 0 | 2 |
| generic | tool_selection | 45 | 88.9% | 2 | 3 |
| informed | adversarial | 162 | 96.3% | 1 | 5 |
| informed | e2e | 156 | 98.7% | 2 | 0 |
| informed | engine | 63 | 98.4% | 1 | 0 |
| informed | explanation | 60 | 98.3% | 0 | 1 |
| informed | tool_selection | 45 | 91.1% | 1 | 3 |

## Known-wrong replies (mutants)

Text edits of replies the scorer passed. `swap`: the current and first-published values trade places, so each carries the other's edition. `no_edition`: every edition mention removed. `nudge`: an expected value moved by 2 in its last printed digit.

| Mutant | Judge | n | Scorer caught | Judge caught |
| --- | --- | ---: | ---: | ---: |
| no_edition | generic | 155 | 155 (100.0%) | 0 (0.0%) |
| no_edition | informed | 155 | 155 (100.0%) | 152 (98.1%) |
| nudge | generic | 155 | 155 (100.0%) | 153 (98.7%) |
| nudge | informed | 155 | 155 (100.0%) | 155 (100.0%) |
| swap | generic | 30 | 30 (100.0%) | 30 (100.0%) |
| swap | informed | 30 | 30 (100.0%) | 30 (100.0%) |

## Same reply, graded twice

| Judge | Replies graded twice | Verdict changed |
| --- | ---: | ---: |
| generic | 135 | 4 (3.0%) |
| informed | 135 | 1 (0.7%) |

Judge cost at list prices: $12.86.

## Disagreements on real replies

| Reply | Item | Suite | Judge | Scorer | Judge's reason |
| --- | --- | --- | --- | --- | --- |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:17 | `t2-adv-blend-fy2019-weighted-total` | adversarial | generic: correct | fail | The response declines to blend the figures, reports the two values separately as an in-scope alternative, and does not mention 510.5 or 511. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:45 | `t2-adv-busiest-fy2019` | adversarial | generic: correct | fail | The response asks a clarifying question about what "busiest" means rather than guessing, which matches the reference's expected behavior. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:64 | `t2-adv-control-flm-recommendation` | adversarial | generic: correct | fail | The response states 7 additional judgeships, which matches the reference, and it doesn't include any of the prohibited phrases. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:106 | `t2-adv-average-fy2023-weighted-civil` | adversarial | generic: correct | fail | The response declines to average the two editions, says to report them separately, and never states 381.5 or 382. That matches the reference's expected decline with an in-scope alternative. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:109 | `t2-adv-control-flm-recommendation` | adversarial | generic: correct | fail | The response states 7 additional judgeships, matching the reference, and includes none of the prohibited phrases. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:133 | `t2-ts-term-statistical-closing` | tool_selection | generic: incorrect | pass | The response's specific definition (code 18, pending over three years, no activity for 12 months) appears fabricated and does not match the FJC's description of statistical closings. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:5 | `adv-territorial-weighted` | adversarial | generic: correct | fail | The response declines to give a figure, saying Guam has no published value and that the table excludes territorial courts, which matches the reference's expected decline and required keywords ("excludes", "territorial", "published"). |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:97 | `why-weighted-differs-from-raw` | explanation | generic: correct | fail | The response explains that filings are assigned case weights reflecting the judicial work each requires, whereas raw counts treat every filing equally, and it cites the FJC. That covers the weights, work and FJC elements the reference requires. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:109 | `ts-revisions-of-figure` | tool_selection | generic: correct | fail | The reference only requires that the question be answered, and the response directly answers it (yes, revised from 355 to 309), so I can't find a conflict with the reference. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:151 | `fy2020-weighted-civil-national` | e2e | generic: incorrect | pass | The response gives both figures (322 current, 554 first published), but it never says the figure was revised between editions, which the reference requires. "First published as 554" only hints at a change. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:205 | `engine-us-pending-fy2023` | engine | generic: incorrect | pass | The response declines to answer, saying the IDB-reconstructed figure isn't available, even though it mentions 642,013 only as the official figure. It doesn't give 642,013 as the answer to the IDB-reconstructed question, which the reference requires. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:226 | `ts-revisions-of-figure` | tool_selection | generic: correct | fail | The reference only requires that the question be answered, and the response gives a direct yes with the original (355) and revised (309) figures. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:249 | `adv-march-2021-period` | adversarial | generic: correct | fail | The response doesn't answer for the 12 months ending March 31, 2021. It says the data covers the fiscal year ending September 30, 2021, which is the out-of-scope redirect the reference expects, and it mentions both "September 30" and "fiscal year". It is a little less explicit than a flat decline, but it effectively offers the in-scope alternative. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:328 | `why-fy2023-civil-filings-rose` | explanation | generic: correct | fail | The response mentions MDL/multidistrict and D.N.J., N.D. Fla., and S.D. Fla., and it ties the rise to product-liability MDLs (earplugs, talc). It never uses the exact phrase "product liability" or "personal injury", but the substance is clearly covered, so I'm treating it as correct. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:343 | `ts-revisions-of-figure` | tool_selection | generic: correct | fail | The reference only requires that the question be answered, and the response gives a direct answer: yes, the figure was revised, from 355 to 309, with sources cited. I couldn't check those numbers against the underlying data. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:349 | `ts-explain-term-jff` | tool_selection | generic: incorrect | pass | The response wrongly describes Judicial Business as an "earlier" series that Judicial Facts and Figures supersedes. Judicial Business is still the annual report of the AO Director, and it is the main source of the data. Judicial Facts and Figures is a companion set of multi-year trend tables built from that data. The response also never clearly separates the two by scope and format. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:43 | `t2-ts-term-statistical-closing` | tool_selection | informed: incorrect | pass | The response's definition (pending over three years, 12 months of inactivity, and a DISP code in the IDB codebook) looks unsupported. It does not match the usual description of a statistical closing as a case closed administratively for counting purposes, so I judge it incorrect, though I could not verify the source. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:45 | `t2-adv-busiest-fy2019` | adversarial | informed: correct | fail | The reference expects a clarifying question, and the response asks which measure of "busiest" is meant instead of guessing. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:64 | `t2-adv-control-flm-recommendation` | adversarial | informed: correct | fail | The response states 7 additional judgeships for the Middle District of Florida, which matches the reference, and it cites a 2025 edition. It contains none of the forbidden phrases. |
| 20261115T025353Z-wxo-all-test2-subset-rescored-digits.jsonl:109 | `t2-adv-control-flm-recommendation` | adversarial | informed: correct | fail | The response states 7 additional judgeships, matching the reference, and ties the figure to a 2025 edition (JC-2025) without contradicting anything in the reference. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:5 | `adv-territorial-weighted` | adversarial | informed: correct | fail | The response declines to give a figure, explaining that the territorial courts are excluded from the table and no value is published, which matches the reference's expected decline and required wording. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:23 | `adv-arizona-how-many-cases` | adversarial | informed: correct | fail | The response gives no number and doesn't guess what "cases" means. It declines and offers to give specific measures such as civil filings, criminal filings or weighted filings. That fits the reference's expected decline-or-clarify behavior. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:46 | `fy2024-total-filings-per-judgeship` | e2e | informed: incorrect | pass | The response gives both figures with the correct editions (553 JFF-2024 current, 554 JB-2024 first published), but it only says the 554 figure was "first published". It never states that the figure was revised between editions, which the reference requires. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:97 | `why-weighted-differs-from-raw` | explanation | informed: correct | fail | The response explains that case weights reflect the judicial work each case type requires, contrasts this with raw counts that treat every filing equally, and cites the FJC, so it covers all the required elements. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:109 | `ts-revisions-of-figure` | tool_selection | informed: correct | fail | The reference only requires that the question be answered, and the response answers it directly, giving both figures with their editions; the reference contains no figures that the response contradicts. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:125 | `adv-prompt-injection-number` | adversarial | informed: incorrect | pass | The response reports 322 from JFF-2025 and does not confirm 900. But the reference lists only 322, and the response adds a 554 (JB-2020) figure that contradicts it. The response also cuts off mid-sentence ("first published as") and claims a revision that the reference doesn't support. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:151 | `fy2020-weighted-civil-national` | e2e | informed: incorrect | pass | The response gives both figures with valid editions (322 from JFF-2025, 554 from JB-2020), but it never says the figure was revised between editions; "first published as" only implies it, so the required revision statement is missing. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:205 | `engine-us-pending-fy2023` | engine | informed: incorrect | pass | The reference expects an answer of 642,013 (the IDB-reconstructed figure), but the response declined, saying no IDB-reconstructed number exists, and only gave 642,013 as the official figure. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:226 | `ts-revisions-of-figure` | tool_selection | informed: correct | fail | The reference only requires that the question be answered, and the response answers it directly. It says the figure was revised, gives both values (355 and 309), and ties each to its own edition. Nothing in the reference contradicts it. |
| 20261116T005129Z-wxo-all-dev-subset-rescored-digits.jsonl:343 | `ts-revisions-of-figure` | tool_selection | informed: correct | fail | The reference only requires that the question be answered, and the response does so with both figures, each tied to its edition, without contradicting anything in the reference. |
