# Personal Data Warehouse — developer commands.
# Spec §17/§18/§27. Default target is a full synthetic pipeline run.
.DEFAULT_GOAL := sync
.PHONY: setup up down migrate seed dbt sync sync-github sync-calendar sync-real \
        reset test psql status clean

# Load .env if present (for local uv-run targets that need DATABASE_URL).
-include .env
export

# --- Stack lifecycle ---
setup: ## One-time: enable docker compose, create .env, install deps, make test db
	@mkdir -p $$HOME/.docker/cli-plugins
	@ln -sf /Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose $$HOME/.docker/cli-plugins/docker-compose 2>/dev/null || true
	@docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose unavailable"; exit 1; }
	@[ -f .env ] || cp .env.example .env
	@echo ">> syncing python deps (uv)"
	cd ingestion && uv sync
	@echo ">> creating test database (idempotent)"
	-@docker compose exec -T postgres psql -U $${POSTGRES_USER:-pdw} -d $${POSTGRES_DB:-pdw} -c "CREATE DATABASE pdw_test;" 2>/dev/null || true
	@echo ">> setup complete. Run: make up && make sync"

up: ## Start PostgreSQL container
	docker compose up -d postgres
	@echo ">> waiting for postgres to be healthy"
	@docker compose exec postgres pg_isready -U $${POSTGRES_USER:-pdw} -d $${POSTGRES_DB:-pdw} >/dev/null

down: ## Stop the stack
	docker compose down

# --- Pipeline (run ingestion locally via uv against containerized postgres) ---
migrate: ## Apply SQL migrations to raw/ops tables
	cd ingestion && uv run pdw migrate

seed: ## Generate + load synthetic data into raw tables (idempotent)
	cd ingestion && uv run pdw seed

dbt: ## Build dbt models + run tests (in container)
	docker compose run --rm dbt build

sync: migrate seed dbt ## Full synthetic pipeline: migrate -> seed -> dbt
	@echo ">> pipeline complete. Try: make status"

# --- Real connectors (require credentials in .env; spec §6) ---
sync-github: migrate ## Sync real GitHub data (needs GITHUB_TOKEN)
	cd ingestion && uv run pdw sync github

sync-calendar: migrate ## Sync real Google Calendar data (needs GOOGLE_* creds)
	cd ingestion && uv run pdw sync calendar

sync-real: sync-github sync-calendar ## Sync both real sources
	@echo ">> real sync complete. Run: make dbt"

reset: ## Truncate raw + analytics so synthetic/real modes don't double-count
	@echo ">> truncating raw + operational tables"
	@docker compose exec -T postgres psql -U $${POSTGRES_USER:-pdw} -d $${POSTGRES_DB:-pdw} -c \
		"TRUNCATE TABLE raw_github_repositories, raw_github_commits, raw_calendar_events, pipeline_runs, sync_state RESTART IDENTITY CASCADE;"
	@echo ">> rebuilding dbt marts"
	docker compose run --rm dbt build
	@echo ">> reset complete."

# --- Quality / inspection ---
test: ## Run pytest (unit + integration)
	cd ingestion && uv run pytest -q

psql: ## Connect to PostgreSQL with psql (in container)
	docker compose exec postgres psql -U $${POSTGRES_USER:-pdw} -d $${POSTGRES_DB:-pdw}

status: ## Show recent pipeline runs
	cd ingestion && uv run pdw status

clean: ## Remove build artifacts and dbt targets
	rm -rf ingestion/.venv ingestion/.pytest_cache ingestion/.ruff_cache
	rm -rf dbt/target dbt/logs