# Guardrails: the rules and how they're applied

Code: [`src/courts_analyst/core/guardrails/`](../../src/courts_analyst/core/guardrails/).
Settings: [`core/data/guardrails.yaml`](../../src/courts_analyst/core/data/guardrails.yaml).
Design: [ADR 0010](../adr/0010-guardrail-policy-layer.md). Security view:
[threat model](../security/threat-model.md).

Every core function that returns data is `@guarded`: its result goes through
`apply_policies` before any adapter sees it. A policy can add a warning,
withhold values, return `status: "declined"` (with the reason, the policy and
its source, and an alternative), or refuse the result outright when a core
invariant was broken.

## Small cells

| Cases | Statistic (median, rate, share, CI) | Count in an IDB breakdown |
| ---: | --- | --- |
| 0 | none to compute ("no cases") | shown as 0 |
| 1–9 | withheld | suppressed (`n: null`, `suppressed: true`) |
| 10–29 | shown, `small_cell` caution | shown |
| 30+ | shown | shown |

A cohort of 1–9 cases shows no count at all ("fewer than 10"), and
`sample_dockets` declines it.

**Complementary suppression.** If a breakdown's cells add up to a total the
result also shows, the smallest visible cells are withheld too, until no
withheld cell can be worked out. The attacker model: the reader knows the
total, every visible cell, that each withheld cell is at least 1, that cells
withheld for being small are at most 9, and that cells withheld to protect
them are at least 10 and no larger than the smallest visible cell. A cell is
recovered when those facts leave one possible value; the property tests check
this with a brute-force enumeration.

`explain_change` breakdowns fold rows under 10 cases in both years into "All
other" (folding one more row where needed) instead of blanking them, so the
rows still sum exactly to the change.

Thresholds are the plan's decision 3 (warn < 30, suppress < 10), pending the
domain expert's confirmation.

## Never mix vintages

A set of official values for several years is **consistent** when (1) they
come from one publication series, Judicial Business or Judicial Facts and
Figures, and (2) no edition used for one year prints a different value for
another year in the set. Pending counts are restated by the next edition as
a matter of course, so for them only a *newer* edition's disagreement counts.

`official_series` and `explain_change` choose, in order: each year's latest
value; the latest single edition printing every year; each year as first
published. The first that is consistent wins, with a `revised_figure` note
when it isn't the latest values. If none is consistent, the request is refused
(`mixed_editions`) with the years and editions that conflict. The caller can
pass `allow_mixed=True`, and then every point carries its edition and the
result a `mixed_editions` caution.

Example: national weighted civil filings per judgeship, FY2016–FY2025. The
latest values splice JFF-2020's pre-revision FY2016 with JFF-2023's revised
FY2019 (JFF-2020 prints FY2019 as 381, JFF-2023 as 332), so the series falls
back to Judicial Business as first published.

## Periods

The catalog holds fiscal years (12 months ending September 30) and, for 1990
only, national statistical-year rows (ending June 30). `get_official_figure`
takes `period_ending`. Any other period returns `out_of_scope`, stating what
the server holds, that uscourts.gov publishes other 12-month tables that
aren't loaded, and the nearest fiscal year with how many months it shares. A
result that mixes a statistical year with fiscal years carries
`period_mismatch`.

## Data breaks

Cohorts and `explain_change` windows that cross an entry in the IDB's
data-break registry (`pipeline/idb/data_breaks.yaml`) carry a `data_break`
caution naming the change and its date. For example, origin 13 (directly
filed MDL cases) begins July 1, 2016, so any window including FY2016 is
flagged for MDL cohorts.

## Revisions and inference

Every official figure carries `citation`, one line that names the edition and
any revision, so "just one number" answers keep it. Any result with a revised
figure carries `revised_figure`; any explanation with an inferred driver
carries `inferred_not_official`. `apply_policies` adds either if a core
function forgot.

## Judge-level analysis, party names, advocacy

- **Structural.** The data has no judge identifiers (Judicial Conference
  policy, March 1995, reaffirmed 2003; the FJC redacts them from the IDB) and
  no party names (kept outside the database). No tool input can name a judge.
- **Request screen.** `intent.screen(text)` flags judge-level and party-name
  requests (declined, with an alternative) and advocacy (answered neutrally).
  It is measured on the whole question bank: every judge-ranking and
  party-name item is caught and no other question is flagged.
- **Output scanner.** Every result is checked against hashed multi-word party
  names; a match withholds it. The server's own vocabulary (court names,
  codebook labels, glossary, tool text, catalog footnotes) is allowed, and
  court names act as phrase boundaries.
- **Neutral wording.** The server's summary sentences (`statement`,
  `headline`) are checked for advocacy phrases, and `judgeship_context`
  carries a `no_recommendation` note.
