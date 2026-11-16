# web/

The Federal Courts Analyst web app: React 19 + TypeScript (strict) + Vite,
TanStack Router/Query, Tailwind v4, Observable Plot. The Python container
serves the build at `/` next to `/api` and `/mcp` (ADR 0005, ADR 0012).

```bash
make serve-http PORT=8000   # the backend (full data), in another terminal
cd web && npm ci && npm run dev   # http://localhost:5173, proxying /api
```

| Command                              | What it does                                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev`                        | Dev server; `/api` proxied to `BACKEND_URL` (default `http://127.0.0.1:8000`)                                             |
| `npx vite build`                     | Production build into `dist/` (served by the Python app)                                                                  |
| `npm run lint` / `npm run typecheck` | ESLint + Prettier / `tsc`                                                                                                 |
| `npm test`                           | Vitest: formatting, SSE client (MSW), turn reducer, chart data, components                                                |
| `npx playwright test`                | Journeys against `vite preview` with a mocked API, with axe on every page                                                 |
| `npx lhci autorun`                   | Lighthouse (performance ≥ 90, accessibility 100)                                                                          |
| `npm run types`                      | Regenerate `src/api/types.gen.ts` from `src/api/schemas` (`make schemas` first); `types:check` fails if stale             |
| `npm run geo`                        | Rebuild `public/geo/districts.topo.json` from us-atlas and `src/geo/county-districts.json` (`make web-geo` rebuilds both) |
| `node e2e/capture-fixtures.mjs`      | Refresh the e2e API fixtures from a running full-data backend                                                             |

Pages: Ask (`/`), Explore (`/explore`), Edition Tracker
(`/editions/{measure}/{court}/{fy}`), court profile (`/courts/{court}`),
Evaluation (`/eval`), Methodology (`/methodology`), presentation mode
(`/demo`, ← → to move, L live, R recorded) and the component gallery
(`/dev/gallery`).
