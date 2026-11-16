# Evaluation document: Security and responsible use (draft)

*Draft for the Phase 11 evaluation document. Numbers are from Phase 6
(2026-09-27); Phase 10 re-runs the held-out split.*

## What the server won't do, and how we know

Federal Courts Analyst answers workload questions about federal district
courts from public data, but some conclusions it refuses to draw. Each rule
is a policy in one layer of the core (`core/guardrails/`), applied to every
tool and, from Phase 7, every REST endpoint. A test fails the build if any
data-returning function skips it.

| Rule | Behaviour | Measured by |
| --- | --- | --- |
| No judge-level analysis | Requests to rank, compare, name or profile judges get a structured decline citing the Judicial Conference's 1995 policy (reaffirmed 2003) and the judge-shopping concern, plus a district-level alternative. No tool can take a judge, and the data has no judge identifiers. | Request screen: 100% recall on 8 judge-ranking items, 0 false positives on 165 other questions; adversarial suite |
| No party names | Names never enter the server's database; an output scanner withholds any result matching a hashed party name (fail closed). | 0 false positives over 867 real results on the full data; `test_pii_scanner.py` |
| Small cells | Statistics on fewer than 10 cases are withheld and 10–29 are cautioned. Complementary suppression means a withheld count can't be recovered by subtraction. | Property tests against a brute-force attacker |
| Never mix vintages | A multi-year series comes from one consistent publication series or is refused, unless mixing is requested and labelled. | `test_no_mixed_vintages.py`; adversarial `adv-latest-each-year-change` |
| Revisions travel with the number | Every official figure carries a one-line `citation` naming its edition and any revision ("322 (JFF-2025, Table 6.2); revised: first published as 554 (JB-2020)"). | Adversarial `adv-one-number-please` |
| No improvised facts about periods | A 12-month period the catalog doesn't hold gets a factual answer: what the server holds, the nearest fiscal year and how many months overlap. | `test_periods.py`; adversarial period items |
| Neutral framing | The server reports workload, thresholds and the Judicial Conference's own recommendation; it never argues for judgeships, and its summary sentences are checked for advocacy. | Adversarial policy items |

**Adversarial suite:** 47 items (judge rankings, party names, advocacy,
out-of-scope courts, years and periods, small cells, prompt injection, mixed
editions, ambiguity, and three over-refusal controls). Phase 5 baseline:
22/26. Phase 6 result with Claude Sonnet: see
[`eval/results/`](../../eval/results/README.md). Decline precision and
recall are reported from the dev and held-out splits separately.

## Security

A STRIDE-lite [threat model](threat-model.md) covers prompt injection, SQL
injection, resource exhaustion, PII, secrets, supply chain, container
privilege and misleading output. Highlights:

- **Injection-resistant by construction.** Closed vocabularies as JSON Schema
  enums, `?` parameters only (checked on the syntax tree), read-only data
  with file access disabled. The server never reads CourtListener text, so
  injected docket text can't reach the figures.
- **Bounded.** 30 s query timeout, 100,000-row cap, 512 KB result budget,
  per-client rate limit, 1 MiB request limit.
- **Hardened HTTP.** Security headers, CORS allowlist (closed by default),
  optional bearer token for the deployed demo.
- **Hardened container.** Non-root, read-only root filesystem, no Linux
  capabilities, data mounted read-only, party names never mounted.
- **Secrets.** Environment only, redacted from every log line;
  `detect-secrets` in pre-commit and CI.
- **Supply chain.** Locked dependencies, `pip-audit` and `bandit` in CI,
  Dependabot. Scans are green at the end of Phase 6.

## Limits we state plainly

The request screen is a pattern classifier, and a user can phrase around it.
That exposes nothing, because the data holds no judge identifiers or party
names; the screen exists to give a clear, sourced refusal. The model is
outside the server's control: the server refuses and labels, and the
evaluation measures how often a model still mis-states a figure.
