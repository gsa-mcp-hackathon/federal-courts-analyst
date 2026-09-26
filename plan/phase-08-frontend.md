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
| `RevisionChip` | Amber chip: "Revised · first published as 554 (JB 2020)". Click opens the Edition Tracker for that figure |
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
3. **Edition Tracker:** pick a measure and court; see the vintage chart and a revision table. Deep-linkable (`/editions/weighted-filings-per-judgeship/national/2020`).
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

- [ ] Scaffold `web/` (Vite, TS strict, ESLint, Prettier, Tailwind, shadcn/ui); CI job enabled
- [ ] Generated API types from backend schemas; typed API client
- [ ] District geometry: build 94-district TopoJSON from US county boundaries (us-atlas) + a county→district crosswalk; commit the built file with its build script
- [ ] Components and pages above
- [ ] Number formatting utilities (per-judgeship, counts, percentages, CIs) with locale and tabular numerals
- [ ] Error boundary + offline/replay mode
- [ ] Production build served by FastAPI; cache headers

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

- [ ] All seven pages complete with loading, empty and error states
- [ ] The FY2020 storyline runs smoothly in both live and replay mode
- [ ] Visual, a11y and performance gates green in CI
- [ ] A reviewer outside the team can answer "which districts are over 600 weighted filings per judgeship, according to which edition?" in under 30 seconds without help
