# syntax=docker/dockerfile:1
# Container image for remote (streamable-HTTP) deployment.
#
# Used by:
#   - IBM Code Engine (deploy/ibm/)
#   - cloud.gov (docker image path) and any other container host
#   - local integration tests (make docker-test)
#
# The server serves MCP over streamable-HTTP at :8080/mcp with a health check
# at :8080/health. app.py auto-selects HTTP because PORT is set below.
#
# Run it hardened (Phase 6; what `make docker-run` and the docker tests do):
#   docker run --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
#     --cap-drop ALL --security-opt no-new-privileges \
#     -v "$PWD/data/build:/app/data/build:ro" federal-courts-analyst:dev
# The app writes nothing outside /tmp (DuckDB spills there). data/private
# (IDB party names) is never mounted; data/build holds only the hashed
# party-name index the output scanner reads.

FROM python:3.12-slim

ARG GIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PORT=8080 \
    DATA_DIR=/app/data \
    GIT_SHA=${GIT_SHA}

WORKDIR /app

# Install uv (fast, reproducible installs from uv.lock).
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

# Dependencies first for better layer caching; exact versions from uv.lock.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Run as an unprivileged user.
RUN useradd --system --uid 10001 app && mkdir -p /app/data && chown -R app /app/data
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1

# PORT=8080 (set above) makes app.py run HTTP on that port automatically.
CMD ["python", "-m", "courts_analyst.app"]
