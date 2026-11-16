# Phase 11: Submission and Demo

**Goal:** turn the work into the three deliverables (repo, slide deck, evaluation document) plus a rehearsed, failure-proof demo.

**Judging impact:** Presentation directly; makes every other criterion visible.

## Deliverables

### 1. GitHub repo
- [ ] README: one-paragraph pitch, 60-second GIF of the Ask page, quickstart (`make setup && make data-sample && make serve`), client configs, architecture diagram, links to the eval doc and deck
- [ ] `docs/`: methodology, ADRs, threat model, variance report, revision log, deploy runbook
- [ ] Clean history, license, CONTRIBUTING, code of conduct (template defaults), CI badges
- [ ] Reproducible data build documented, with expected runtimes

### 2. Slide deck (about 12 slides)
1. The question everyone asks: "How busy are the federal courts?"
2. Four official answers for FY2020 (676 / 675 / 554 / 322), the hook
3. Why AI gets this wrong today (web search mixes vintages; no MCP server has aggregate stats)
4. Our solution in one sentence + architecture
5. Tool design: goal-oriented tools, Pydantic, output schemas, cohort handles (per the 2026-07-28 spec)
6. Provenance on every answer (badge anatomy)
7. Guardrails: what the server refuses to conclude, and why
8. Live demo (or recorded fallback)
9. Evaluation methodology
10. Results: lift over web search and Genie, across models
11. Mission alignment and neutral framing; who uses it
12. Lessons learned + what's next (criminal/appellate, AO confirmation of the revision)

### 3. Evaluation document
- [ ] Methodology (question bank, splits, deterministic scoring, baselines, ablations, statistics)
- [ ] Metrics and results with CIs; error taxonomy analysis
- [ ] Security (threat model, guardrails, PII handling, scans)
- [ ] Limitations and honest caveats (inferred explanations, reconciliation gaps, scope)
- [ ] Lessons learned
- [ ] Appendix: full results tables, Genie setup, prompts, tool descriptions

## Demo (about 5 minutes)

Follows the concept's storyline, run from the web app's presentation mode:

1. "Why did federal civil filings jump in FY2020?" → clarify chips (all civil vs weighted-eligible)
2. `explain_change` → waterfall: N.D. Fla. directly filed 3M earplug MDL cases, with provenance and reconciliation badges
3. Vintage chart: weighted figure 554 (JB 2020) vs 322 (JFF 2023+), revision flagged, explanation labeled *inferred*
4. Three real dockets via CourtListener, including the MDL master docket
5. "Rank the judges in N.D. Fla." → declines and explains why
6. Switch to Claude Desktop: same question, inline MCP App chart (cross-client proof)
7. Close on the eval dashboard: lift over web search and Genie

**Demo insurance:** a recorded event stream for every step (replay mode), a pre-recorded video, local server fallback, and screenshots in the deck.

## Tasks

- [ ] AO statistics staff review of the storyline and revision narrative (framing: "the server never mixes series")
- [ ] Demo script with timings; three full rehearsals, one with a deliberate network failure
- [ ] Record a 3–5 minute demo video (captions on)
- [ ] Deck design matches the web app's design system
- [ ] Final freeze: tag release `v1.0.0`, DB build hash recorded, deployed URLs verified the day before

## Tests / checks

| Check | How |
| --- | --- |
| Fresh-clone quickstart | Someone outside the team follows the README on a clean machine; time it (target < 15 min with sample data) |
| Link check | Automated link checker over README, docs, deck links |
| Numbers audit | Every number in the deck and eval doc traced to a results file or golden figure (checklist) |
| Demo dry-run | Full run live + full run in replay mode, both under 5:30 |
| Accessibility | Deck and video captions; eval doc readable as tagged PDF |

## Exit criteria

- [ ] All three deliverables submitted before the deadline, with at least 48 hours of buffer
- [ ] Demo rehearsed including a failure drill
- [ ] AO review done (or explicitly waived by the team)
