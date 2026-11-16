# ADR 0005: Frontend served from the Python container

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The web app (P8) is a React + Vite single-page app. It could be hosted on its
own (a CDN or cloud.gov static site) or served by our Python app. Our primary
deploy target, Databricks Apps, runs **one** app process per deployment behind
workspace auth. The hackathon also wants a demo that's simple to stand up.

## Decision

Build the SPA to static files (`web/dist`) and serve them from the FastAPI app
(P7) in the same container as the MCP endpoint and REST API. The container
build becomes multi-stage: a Node stage builds `web/`, and the Python stage
copies `web/dist` in.

Routes: `/mcp` (MCP), `/api/*` (REST + SSE), `/health` and `/version`, and
everything else goes to the SPA with an `index.html` fallback.

## Consequences

- One image, one deploy, one URL, and no CORS configuration.
- Databricks Apps auth covers the UI and the API together.
- Frontend changes need an image rebuild to deploy. Local development still uses
  Vite's dev server with a proxy to the Python app.
- The MCP App bundle (P9) is built from the same `web/` workspace, so the chart
  components are shared.
