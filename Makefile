# Federal Courts Analyst — developer entry points. Run `make help`.
.DEFAULT_GOAL := help
.PHONY: help setup lint format typecheck test test-full cov data data-tables \
        data-discover data-idb data-idb-sample serve serve-http \
        variance-report schemas inspector docker-build docker-run docker-test web eval eval-validate eval-claude clean

IMAGE ?= federal-courts-analyst:dev
PORT  ?= 8000

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install dev deps and git hooks
	uv sync --group dev --group pipeline
	@if [ -d .git ]; then uv run pre-commit install; fi
	@[ -f .env ] || cp .env.example .env

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy (strict on core/ and models.py)
	uv run mypy

test: ## Fast test suite with coverage (no full-data tests)
	uv run pytest --cov --cov-report=term-missing --cov-report=xml

test-full: ## Everything, including @fulldata tests (needs `make data`)
	uv run pytest -m "" --cov --cov-report=term-missing

data: data-tables data-idb ## Download and build every dataset

data-tables: ## Fetch the official tables in the manifest and build courts.duckdb
	uv sync --group dev --group pipeline
	uv run python -m courts_analyst.pipeline.tables all

data-idb: ## Fetch the pinned civil IDB release (~330 MB) and build idb.duckdb (~1.5 min)
	uv sync --group dev --group pipeline
	uv run python -m courts_analyst.pipeline.idb all

data-idb-sample: ## Rebuild the committed IDB test fixture from the downloaded release
	uv run python -m courts_analyst.pipeline.idb sample

variance-report: ## Reconcile every court-year (IDB vs Table C-1) into docs/variance-report.md
	uv run python -m courts_analyst.pipeline.reports variance

schemas: ## Export result JSON Schemas for the frontend (web/src/api/schemas/)
	uv run python -m courts_analyst.schemas

data-discover: ## Re-crawl uscourts.gov and rewrite data/manifest/tables.yaml
	uv run python -m courts_analyst.pipeline.tables discover

serve: ## Run the MCP server over stdio
	uv run courts-analyst

serve-http: ## Run the MCP server over streamable HTTP on $(PORT)
	MCP_TRANSPORT=streamable-http MCP_PORT=$(PORT) uv run courts-analyst

inspector: ## Open the MCP Inspector against the stdio server
	npx -y @modelcontextprotocol/inspector uv run courts-analyst

docker-build: ## Build the container image
	docker build --build-arg GIT_SHA=$$(git rev-parse --short HEAD) -t $(IMAGE) .

docker-run: docker-build ## Run the container on :8080
	docker run --rm -p 8080:8080 $(IMAGE)

docker-test: docker-build ## Integration tests against the running container
	uv run pytest -m docker tests/test_docker.py -v

web: ## Frontend dev server (P8)
	@echo "make web: the frontend arrives in Phase 8."

eval-validate: ## Validate the question bank (schema, ids, splits)
	uv run courts-eval validate

eval-claude: ## Dev-split tool-selection + e2e run with Claude (needs a logged-in `claude` CLI)
	uv run courts-eval run --answerer claude-code --suite tool_selection --split dev --workers 4
	uv run courts-eval run --answerer claude-code --suite e2e --split dev --workers 4

eval: ## Harness self-check: gold must score 100%, null 0%
	uv run courts-eval run --answerer gold --quiet --expect-accuracy 1
	uv run courts-eval run --answerer null --quiet --expect-accuracy 0

clean: ## Remove caches and build outputs (keeps downloads in data/raw)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find data/build -mindepth 1 ! -name .gitkeep -delete
	rm -rf data/private
