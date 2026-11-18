# Phase 8: Web Frontend

**Goal:** a web app that looks like first-rate data journalism and behaves like a careful analyst. Every number on screen can be traced to its table and edition in one click. This is our demo surface and the thing judges will remember.

**Judging impact:** Presentation (smooth, beautiful demo), mission alignment (usable by staffers, journalists and researchers), innovation (provenance-first UI, vintage chart).

## Stack

| Concern | Choice |
| --- | --- |
| Framework | React 19 + TypeScript (strict) + Vite |
| Routing and data | TanStack Router (typed routes, URL state for filters) + TanStack Query |
| Styling | Tailwind CSS v4 with design tokens as CSS variables; shadcn/ui on Radix primitives |
| Charts | Observable Plot for statistical charts; d3-geo + TopoJSON for the district map |
| Motion | Motion (Framer) for small, purposeful transitions; respects `prefers-reduced-motion` |
| Streaming | Native `EventSource`/fetch-stream client for our typed SSE protocol |
| Types | Generated from the backend's JSON schemas (`make schemas`), so API drift fails the build |
| Build output | Static files served by the Python container |

## Design direction

**"Official record, modern instrument."** Calm, editorial and trustworthy, closer to the FT or Our World in Data than a SaaS dashboard.

- **Type:** Public Sans (the USWDS typeface, a quiet nod to GSA judges) for UI; Source Serif 4 for headlines and narrative answers; tabular numerals for every figure (IBM Plex Mono for codes and cell refs).
- **Color:** warm paper background, ink-navy text, one institutional blue accent. A dedicated **revision amber** used *only* for "this figure was revised" so it becomes a recognizable signal. Status colors for reconciliation (matched / explained / unexplained) chosen with the dataviz palette validator. Full dark mode.
- **Layout:** generous whitespace, 12-column grid, narrative left + evidence right on wide screens, single column on mobile.
- **Accessibility:** WCAG 2.1 AA / Section 508: keyboard navigable, visible focus, charts with text alternatives and data tables, color never the only signal.
- **Voice:** plain language, neutral, no hype. Numbers first, then what they mean, then caveats.

## Signature components

| Component | What it does |
| --- | --- |
| `ProvenanceBadge` | Small pill beside every number ("JFF 2023 · Table 6.2"). Hover/focus opens a card with series, edition, period, definition, cell reference, source link, and "copy citation" |
| `RevisionChip` | Amber chip: "Revised · first published as 554 (JB 2020)" (the result's `citation`). Click opens the Edition Tracker for that figure |
| `DeclineCard` | For `status: "declined"`: the message, the policy with its source, and the alternative as a one-click follow-up |
| `SuppressedCell` | "fewer than 10" for `n: null` / `suppressed: true`, with a tooltip explaining small-cell rules |
| `ReconciliationBadge` | Matched / explained variance / unexplained, with the variance explanation on hover |
| `WarningCallout` | Guardrail warnings (small cell, data break, period mismatch, inferred) in consistent, non-alarming styles |
| `VintageChart` | **The hero visual.** X = fiscal year, one line per edition. Where editions disagree, the gap is shaded amber and annotated. The 554 → 322 story in one picture |
| `ContributorWaterfall` | `explain_change` as a waterfall: start value → top contributors (N.D. Fla. MDL…) → end value, with driver tags |
| `DistrictMap` | The 94 districts shaded by weighted filings per judgeship with 430/600 threshold bands; territories as insets; click to open a court profile |
| `ToolTrace` | "Show your work" timeline of the agent's tool calls, arguments and results, collapsible |
| `ClarifyChips` | Renders elicitation choices as buttons inside the chat |
| `DocketCard` | CourtListener result, clearly labeled external and "match may be inexact"; plain-text rendering only |
| `CohortPill` | Shows the active cohort handle with its filters; click to refine |

## Pages

1. **Ask** (home): a single question box with example questions. Streaming answer in serif, citations inline, charts and docket cards in the evidence rail, `ToolTrace` below. Shareable URL per conversation (replayed from stored events).
2. **Explore:** district map + sortable ranking table, fiscal year slider, edition selector ("current" vs "as first published"), measure toggle (raw vs weighted).
3. **Edition Tracker:** pick a measure and court; see the vintage chart and a revision table. The chart plots one consistent series per line (`official_series`, Phase 6); when the server refuses a mixed series, show why instead of splicing. Deep-linkable (`/editions/weighted-filings-per-judgeship/national/2020`).
4. **Court profile:** a district's caseload profile: trends, NOS mix, median time to disposition, judgeship context against thresholds, recent revisions, reconciliation status.
5. **Evaluation:** results dashboard from P10: accuracy by suite, lift over web search and Genie, per-model comparison, error taxonomy, latency. Numbers link to the individual scored items.
6. **Methodology:** glossary, data sources, editions explained, guardrail policies, limitations. Rendered from the same Markdown the MCP resources serve.
7. **Presentation mode (demo insurance):** `/demo` walks through the demo storyline step by step with keyboard control, driven by either the live agent or a recorded event stream. If the network fails on stage, we switch to replay without anyone noticing.

## Sub-phases

- **8a Design system (can start during P4):** tokens, typography, color validation, core components with mock data, a component gallery page (`/dev/gallery`)
- **8b Explorer pages:** Explore, Edition Tracker, Court profile, Methodology over REST
- **8c Ask experience:** SSE client, streaming rendering, tool trace, clarify round-trip, docket cards
- **8d Evaluation page + presentation mode**
- **8e Polish:** empty/loading/error states, skeletons, motion, mobile, dark mode, performance pass

## Tasks

- [x] Scaffold `web/` (Vite, TS strict, ESLint, Prettier, Tailwind; Radix primitives instead of generated shadcn/ui); CI job enabled
- [x] Generated API types from backend schemas; typed API client
- [x] District geometry: 94-district TopoJSON from us-atlas counties + a county→district crosswalk (derived from the IDB); built file and build scripts committed
- [x] Components and pages above
- [x] Number formatting utilities (per-judgeship, counts, percentages, CIs) with tabular numerals
- [x] Error boundary + offline/replay mode
- [x] Production build served by the Python app; cache headers

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| Component tests | Vitest + Testing Library | `ProvenanceBadge` shows edition/table and opens its card on keyboard focus; `RevisionChip` renders only when `revision_status = revised`; `WarningCallout` variants |
| Formatting tests | Vitest | Numbers, CIs and suppressed values (`suppressed` never renders as 0) |
| SSE client tests | Vitest + MSW | Reassembles a recorded event stream into the correct UI state; handles reconnect and `error` events |
| Chart data tests | Vitest | `VintageChart` builds the right series from a revision payload; `ContributorWaterfall` sums to the total |
| Schema drift | CI | Regenerating types from the backend produces no diff |
| E2E journeys | Playwright (mocked API) | Ask → clarify → answer with citations; Explore → click district → profile; Edition Tracker deep link; Eval page loads |
| E2E live | Playwright (live backend, nightly) | FY2020 storyline end to end |
| Visual regression | Playwright screenshots | Key pages and components in light and dark mode, desktop and mobile |
| Accessibility | axe-core in Playwright | No serious/critical violations on every page |
| Performance | Lighthouse CI | Performance ≥ 90, Accessibility 100 on Explore and Ask (mocked) |

## Exit criteria

- [x] All seven pages complete with loading, empty and error states
- [x] The FY2020 storyline runs smoothly in both live and replay mode (live: Phase 7 curl transcript; replay: `/demo`, checked in Chrome and by Playwright)
- [x] Visual, a11y and performance gates green in CI: a11y (axe, every page, both themes) and Lighthouse gates; visual baselines moved to [#42](https://github.com/syedaun-techsur/federal-courts-analyst/issues/42)
- [ ] A reviewer outside the team can answer "which districts are over 600 weighted filings per judgeship, according to which edition?" in under 30 seconds without help ([#41](https://github.com/syedaun-techsur/federal-courts-analyst/issues/41); needs a person. The page answers it in one view: "20 of 91 districts over 600, all from JB 2025, Table X-1A")

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| shadcn/ui on Radix | Our own components on Radix primitives (`radix-ui`) | A small set, and the signature components (provenance, revisions, declines, suppression) are ours anyway ([ADR 0012](../docs/adr/0012-web-app.md)) |
| County → district crosswalk | Derived from the IDB: each county's majority district among its own state's, weak majorities smoothed from neighbours; `python -m courts_analyst.pipeline.geo` + `npm run geo` | No machine-readable crosswalk ships with our data; the result is reproducible, its weak spots are reported, and the page and methodology say it's approximate ([#44](https://github.com/syedaun-techsur/federal-courts-analyst/issues/44)) |
| `VintageChart`: one line per edition | Plus a new core function and endpoint, `edition_vintages` (`/api/figures/{m}/{c}/editions`): each edition's own series, labelled `mixed_editions` (info) by the guardrail; lines are the editions that printed the selected year; revisions are amber bands per year | `official_series` with one edition refuses years the edition doesn't print (JFF editions print rolling windows); per-year bands avoid implying a trend between revised years |
| Court profile: NOS mix, reconciliation | New endpoints `/api/courts/{c}/case-mix` (find_cases + analyze_cohort) and `/api/courts/{c}/reconcile` | The page needed them over REST; both call guarded core functions |
| Methodology from the MCP resources | New `/api/methodology`, `/api/methodology/{topic}`, `/api/glossary` over the same files and data | REST had no route to them |
| Shareable URL per conversation | `/ask/{turn_id}` replays from this browser's storage | Server-side transcripts need storage and a retention policy ([#45](https://github.com/syedaun-techsur/federal-courts-analyst/issues/45)) |
| Visual regression in CI | Not yet | Baselines are OS-specific; darwin baselines fail on Linux runners ([#42](https://github.com/syedaun-techsur/federal-courts-analyst/issues/42)) |
| E2E live nightly | Hook only (`BACKEND_URL` project) | Needs data and a model key in CI ([#43](https://github.com/syedaun-techsur/federal-courts-analyst/issues/43), [#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18)) |
| Lighthouse on Explore and Ask (mocked) | CI: Ask, presentation mode, gallery on `vite preview`; Explore, Edition Tracker, court profile measured against the full-data server | The data pages have nothing to show without an API; mocked data in Lighthouse would measure the mock |
| — | Page CSP served by the static app (`api/web.py`); `/api` and `/mcp` keep `default-src 'none'`; SPA fallback for deep links; hashed assets immutable | Closes [#38](https://github.com/syedaun-techsur/federal-courts-analyst/issues/38) |
| — | Multi-stage Dockerfile builds the web app (ADR 0005) | One image serves everything |

## Evidence

**Pages (Chrome, full data, light and dark):** Explore with "Over 600": "20 of 91 districts over 600, all from JB 2025, Table X-1A", with the revision note on the national figure ([screenshot](../docs/evidence/phase-08/explore-over-600.jpg)); Edition Tracker FY2020: 322 (JFF-2025) with the revision chip, both revision notes, every edition's line and nine amber revised years ([screenshot](../docs/evidence/phase-08/edition-tracker-fy2020.jpg)); N.D. Fla. profile: 35,559 weighted filings per judgeship in FY2020 against the 430/600 thresholds, trends, case mix with small groups withheld, the official-vs-IDB reconciliation "Matched" ([screenshot](../docs/evidence/phase-08/court-profile-fl-n.jpg)); presentation mode replaying the Phase 7 storyline: the answer, waterfall with hover, three docket cards ([screenshot](../docs/evidence/phase-08/presentation-fy2020-replay.jpg)). No console errors.

**CI:** green on [PR #46](https://github.com/syedaun-techsur/federal-courts-analyst/pull/46) (lint, security, test 3.11, test 3.12, docker, web). The first web run failed Lighthouse on the Ask page (performance 0.61: layout shift from a late font swap, plus a cold-runner first run); both text fonts are now preloaded and the gate uses the median of 3 runs (CLS 0, performance 100).

**Automated tests:** Vitest 40 passed (formatting, SSE parser and stream client with MSW, turn reducer, vintage and waterfall data including a 300-case property test, map bins, components). Playwright 11 passed: 8 journeys on desktop (light) and 3 on mobile (Pixel 7, dark), axe WCAG 2.1 AA with no serious or critical violations on every page. Python 1,032 passed (up from 1,018), coverage **93.7%**; `test_web_app.py` covers the SPA fallback, cache headers, the page CSP vs the API CSP, path traversal, the new endpoints, vintages against the figure's own edition history, and the crosswalk. `make docker-test` 8/8, now including the web app at `/` and a deep link from the hardened container. ESLint, Prettier, `tsc`, ruff, mypy clean; `npm audit --omit=dev` 0 vulnerabilities; pip-audit, bandit, detect-secrets clean.

**Lighthouse (desktop):** Ask 94 / 100 / 100 / 91 (performance / accessibility / best practices / SEO), presentation mode 100 / 100 / 100 / 91, gallery 100 / 100 / 100 / 91 (`vite preview`); on the full-data server Explore 92 / 100 / 100 / 100, Edition Tracker 90 / 100 / 100 / 100, court profile 90 / 100 / 100 / 100. Bundle: main 142 KB gzipped; the chart library (96 KB) loads with the first chart.

**Found and fixed during the phase:**
- The vintages endpoint was refused by the Phase 6 guardrail (JB and JFF values without a `mixed_editions` label): the core now labels it.
- The first revision shading compared against the newest edition only and drew one area across years (a misleading triangle between FY2020 and FY2025); now per-year bands against the newest edition printing each year.
- The type generator dropped a field literally named `title` (ChartSpec) while stripping Pydantic's per-field titles.
- Plot's inner `aria-label`s are prohibited inside `role="img"` (axe); removed.
- Layout shift on the data pages (skeletons smaller than their charts; a monospace line re-wrapping when its font loaded): CLS 0.30 → 0.13, performance 77 → 90.
- A no-wrap citation line became an unfocusable scroll region on mobile (axe, mobile project).
- The SSE parser didn't emit a final event without a trailing blank line.
- Replay paced by fixed sleeps fell far behind in throttled tabs; now paced against a clock.
- Territory tiles overlapped Florida.

## Open issues

Live status is on the [issue tracker](https://github.com/syedaun-techsur/federal-courts-analyst/issues).

1. **Outside-reviewer 30-second test.** [#41](https://github.com/syedaun-techsur/federal-courts-analyst/issues/41)
2. **Visual regression baselines.** [#42](https://github.com/syedaun-techsur/federal-courts-analyst/issues/42)
3. **Nightly live e2e (FY2020 storyline).** [#43](https://github.com/syedaun-techsur/federal-courts-analyst/issues/43)
4. **Exact county lists for the district map.** [#44](https://github.com/syedaun-techsur/federal-courts-analyst/issues/44)
5. **Shareable answer links.** [#45](https://github.com/syedaun-techsur/federal-courts-analyst/issues/45)
6. [#38](https://github.com/syedaun-techsur/federal-courts-analyst/issues/38) (CSP for HTML pages): done; close with this phase's PR.
