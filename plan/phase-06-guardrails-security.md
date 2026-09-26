# Phase 6: Guardrails and Security

**Goal:** the server knows which conclusions it shouldn't draw. Guardrails are implemented once, as a policy layer in the core, and apply identically to MCP tools and the REST API. This phase also produces the security section of the evaluation document.

**Judging impact:** Innovation (our strongest angle), mission alignment (responsible use of court data), and the security section of the eval doc.

## Guardrail policies

Implemented in `core/guardrails/`, one module per policy, each returning `Warning`s or raising `Declined`.

| Policy | Rule | Behavior |
| --- | --- | --- |
| Small cells | n < 30 → warn; n < 10 → suppress the value (thresholds in config, confirmed with the domain expert) | Returns the result with `small_cell` warning, or replaces values with `suppressed` and explains why |
| Complementary suppression | Prevent recovering a suppressed cell by subtracting from totals | When one cell in a breakdown is suppressed, suppress the next-smallest too |
| Data breaks | Query window crosses an entry in `data_breaks` | `data_break` caution with the specific change and date |
| Revised figures | Figure has later revisions | `revised_figure` info; never mixes editions in one series silently (a series built from mixed editions is refused unless explicitly requested and labeled) |
| Period mismatch | Comparing fiscal year with statistical year, or Sep-30 with Mar-31 periods | `period_mismatch` caution |
| Inferred vs official | Any driver or explanation we inferred | `inferred_not_official` label, always |
| No judge-level analysis | Requests to rank, name or compare individual judges (detected by input schema, since no judge field exists, and by an intent check in the agent) | `Declined` with an explanation citing the FJC policy and judge-shopping concerns, plus a suggested alternative (district-level analysis) |
| No advocacy | Requests like "prove district X needs more judges" | Answers with neutral, source-tagged facts; `judgeship_context` never recommends |
| PII | Party names never leave the DB (P2 isolation); docket refs from `sample_dockets` contain case numbers only | Enforced structurally + an output scanner that fails closed |
| Scope | Years, courts or case types outside the loaded data | `out_of_scope` with what *is* available |

## Security

### Threat model (`docs/security/threat-model.md`, STRIDE-lite)
| Threat | Mitigation |
| --- | --- |
| Prompt injection via CourtListener docket text or opinion snippets | Treat external content as data: the agent's system prompt marks it untrusted; our server never ingests CourtListener content; the web UI renders it as plain text |
| SQL injection via tool args | Pydantic enums + parameterized SQL + read-only DuckDB connection (test enforced in P4) |
| Resource exhaustion (huge cohorts, expensive decompositions) | Query timeouts, row limits, output size budget, per-session rate limits in HTTP mode |
| PII leakage | Structural isolation, output scanner, synthetic names in fixtures |
| Secrets exposure | Keys only via env/secret scopes; never logged; `detect-secrets` in pre-commit and CI |
| Supply chain | Pinned deps via `uv.lock`, `pip-audit` and `npm audit` in CI, Dependabot |
| Misleading output | Provenance on every number, reconciliation badges, the "never mix vintages" rule |

### Hardening tasks
- [ ] HTTP mode: CORS allowlist, security headers, request size limits, optional bearer token for the deployed demo
- [ ] Logging: tool arguments logged as hashes by default; no raw user prompts in server logs unless debug is enabled
- [ ] `pip-audit`, `bandit`, `detect-secrets`, `npm audit` jobs in CI
- [ ] Container runs as non-root, read-only filesystem except a temp dir

## Tasks

- [ ] Guardrail policy modules + a single `apply_policies(result, context)` entry point called by every core function that returns data
- [ ] Output PII scanner (names list from `idb_parties` hashed; flags any match in outputs)
- [ ] Judge-request intent detection (a small keyword/pattern classifier, plus an eval-measured agent-level instruction)
- [ ] Threat model and security section draft for the eval doc
- [ ] Adversarial eval suite expanded to ≥ 40 items

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_small_cell.py` | unit, hypothesis | Boundary behavior at 9/10/29/30; suppressed values never appear in output JSON |
| `test_complementary_suppression.py` | property | For random breakdowns with a suppressed cell, no suppressed value can be recovered from totals and visible cells |
| `test_data_breaks.py` | unit | Windows crossing Jul 2016 origin-code change get a caution; windows after it don't |
| `test_no_mixed_vintages.py` | unit | Building a series across editions without `allow_mixed=True` raises; with it, every point carries its edition |
| `test_judge_declines.py` | MCP + unit | "Rank judges in S.D.N.Y. by time to disposition" → `Declined` with explanation and alternative |
| `test_pii_scanner.py` | unit | Output containing a known party name fails closed |
| `test_injection_corpus.py` | integration | A corpus of injected docket texts through the agent (P7) doesn't change tool arguments or cause policy violations |
| `test_http_hardening.py` | API | CORS, headers, size limits, auth when enabled |
| Adversarial eval | eval | Decline/clarify precision and recall ≥ 0.9 on dev; reported on test in P10 |

## Exit criteria

- [ ] Every data-returning core function passes through `apply_policies` (test asserts via a registry)
- [ ] Adversarial suite dev results meet the threshold
- [ ] Threat model and security scans green in CI
