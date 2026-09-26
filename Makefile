# Federal Courts Analyst — developer entry points. Run `make help`.
.DEFAULT_GOAL := help
.PHONY: help setup lint format typecheck test test-full cov data serve serve-http \
        inspector docker-build docker-run docker-test web eval clean

IMAGE ?= federal-courts-analyst:dev
PORT  ?= 8000

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

setup: ## Install dev deps and git hooks
	uv sync --group dev
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

data: ## Download and build the datasets (P1/P2)
	@echo "make data: pipelines arrive in Phase 1 (tables) and Phase 2 (IDB)."

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

eval: ## Run the evaluation benchmark (P3)
	@echo "make eval: the benchmark arrives in Phase 3."

clean: ## Remove caches and build outputs (keeps downloads in data/raw)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find data/build -mindepth 1 ! -name .gitkeep -delete
