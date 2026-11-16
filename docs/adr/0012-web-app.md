# ADR 0012: Web app: typed from the backend schemas, charts from validated tokens, a derived district map

- **Status:** Accepted
- **Date:** 2026-09-27

## Context

Phase 8 builds the demo surface: Ask (the agent), Explore (map and ranking),
the Edition Tracker, court profiles, Evaluation, Methodology and a
presentation mode. It must never show a number without its edition, never
splice editions, stay accessible (WCAG 2.1 AA), run from the one container
(ADR 0005), and survive a network failure on stage.

## Decision

1. **React 19, TypeScript strict, Vite, TanStack Router and Query, Tailwind
   v4.** Code-based routes (typed params and search), one lazy chunk per page;
   the chart library loads with the first chart.
2. **Types come from the backend.** `make schemas` exports JSON Schema
   (Pydantic); `npm run types` turns it into `types.gen.ts`; CI fails if
   either is stale. Every field is typed as present (the server dumps
   defaults and nulls), so the UI can't silently miss one.
3. **Components on Radix primitives, written in this repo** (popover,
   tooltip, toggle group, slider, collapsible), not generated shadcn/ui: the
   set is small, and provenance, revision, decline and suppression components
   are ours anyway.
4. **Charts: Observable Plot, colors from resolved design tokens.** Ramps
   and poles were checked with the dataviz palette validator for both
   surfaces; amber is reserved for "revised". Every chart has a caption
   naming its source, a hover layer, and a data-table view; Plot's internal
   ARIA labels are removed inside `role="img"`.
5. **The Edition Tracker draws one line per edition, as printed** (new
   `edition_vintages` core function and endpoint), plus the server's
   first-published series; revisions are amber bands per year, never an area
   joining years. The core labels the result `mixed_editions` (info) because
   it holds JB and JFF values side by side; the guardrail requires that.
6. **District map from a derived crosswalk.** us-atlas counties (Albers USA)
   merged by county → district, where each county goes to the district most
   of its IDB civil filings went to within its own state, with neighbour
   smoothing for weak majorities; territories are tiles. The page and the
   methodology say it's approximate; the ranking table is exact.
7. **Agent stream over `fetch`** (EventSource can't POST), with a pure
   reducer from events to UI state; the same reducer replays recorded
   streams. Presentation mode (`/demo`) plays a recording or the live agent
   and falls back to the recording if the live stream fails.
8. **Pages get their own CSP** (`self` for scripts, styles, fonts and
   requests; inline style attributes for SVG), set by the static app; `/api`
   and `/mcp` keep `default-src 'none'`. Model and CourtListener text is
   rendered as text only: a small Markdown renderer builds React elements,
   links are limited to http(s) and site paths, docket links to
   courtlistener.com.

## Consequences

- API drift breaks the frontend build, not the demo.
- The map can misplace a few border counties (issue #44); nothing numeric
  depends on it.
- Answer links replay from the browser's storage only (issue #45).
- Visual regression baselines are platform-specific and are not in CI yet
  (issue #42); axe and Lighthouse gates are.

## Alternatives considered

- **Vega-Lite / Recharts** for charts: Plot is smaller for these forms and
  closer to d3 for the map; the map itself is plain SVG so it stays keyboard-
  and screen-reader-simple.
- **A county → district table typed from the statutes**: exact, but 94
  districts' county lists by hand is error-prone without review; the derived
  crosswalk is reproducible and its weak spots are reported.
- **Server-sent `EventSource` with a GET and a session id:** works, but the
  question would sit in URLs and logs.
