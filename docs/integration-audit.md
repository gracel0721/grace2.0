# Personal Developer OS — Integration Audit (Phase 0)

This document is the Phase 0 deliverable for `personal-developer-os` per `spec2.md` §50. It inventories the four existing projects, identifies reusable modules, surfaces duplicate functionality, and proposes a unified architecture and migration order. **No code is rewritten here** — the goal is to enable informed architectural decisions in Phase 1.

---

## Top-of-Doc Summary

**The four projects.**

| # | Project | Path | One-line description |
|---|---|---|---|
| 1 | `error-explainer` | `/Users/gvleverett/Desktop/error-explainer` | Go CLI that turns error messages, stack traces, and logs into structured explanations via a local Ollama LLM, with optional repo source extraction and Qdrant-backed error history. |
| 2 | `webwatch` (`web-change-monitor`) | `/Users/gvleverett/Desktop/web-change-monitor` | Go CLI + Python polyglot monitor that crawls websites on a schedule, diffs snapshots, and uses a local Ollama LLM (via Python) to summarize and rate detected changes. |
| 3 | `codebase-explainer-agent` (`code-explain`) | `/Users/gvleverett/Desktop/codebase-explainer-agent` | Python Typer CLI that builds a tree-sitter AST index of a codebase, embeds chunks with Ollama, and provides streaming RAG answers, hybrid search, a caller/callee graph, and a Stage-3 tool-calling agent for code edits. |
| 4 | `grace2.0` (Personal Data Warehouse) | `/Users/gvleverett/Desktop/grace2.0` | Python+SQL+dbt stack that ingests personal activity (GitHub repos/commits/PRs/issues, Google Calendar, Gmail metadata, Spotify plays) into Postgres, transforms via dbt into marts, and exposes structured activity analytics. |

**Recommended parent-repo layout** (per `spec2.md` §6, adapted to preserve the four projects):

```
personal-developer-os/
├── README.md
├── docker-compose.yml            # postgres + pgvector + dbt + assistant-api + web
├── .env.example                  # unified secrets (see Appendix)
├── Makefile                      # pdo CLI shortcuts
│
├── apps/
│   ├── cli/                      # `pdo` Typer CLI (Phase 5)
│   └── api/                      # FastAPI assistant-api (Phase 6)
│
├── agent/                        # agent loop, planner, prompts, tool registry (Phase 3-4)
│
├── services/
│   ├── knowledge/                # KnowledgeService (notes/RAG/vectors; pgvector-backed)
│   ├── developer/                # DeveloperService (wraps code-explain via subprocess/Python API)
│   ├── errors/                   # ErrorService (wraps error-explainer; Go subprocess + HTTP)
│   ├── monitoring/               # MonitoringService (wraps webwatch; Go subprocess + JSON contract)
│   └── analytics/                # AnalyticsService (reads PDW marts via SQLAlchemy/psycopg)
│
├── integrations/
│   ├── github/                   # PDW GitHub connector (already in grace2.0)
│   ├── calendar/                 # PDW Google Calendar connector
│   ├── gmail/
│   └── spotify/
│
├── data/
│   ├── ingestion/                # PDW `pdw` CLI and connectors (preserved)
│   ├── dbt/                      # PDW dbt models (preserved)
│   └── warehouse/                # Postgres + pgvector init scripts
│
├── storage/
│   ├── postgres/                 # init SQL: warehouse, assistant, knowledge schemas
│   └── vector/                   # pgvector bootstrap
│
├── tests/
└── docs/
    ├── architecture.md
    ├── tools.md
    ├── memory.md
    └── integration-audit.md      # this document
```

The four projects are vendored (or kept as siblings and referenced via path) under their natural homes: `services/errors/` keeps `error-explainer/`, `services/monitoring/` keeps `web-change-monitor/`, `services/developer/` keeps `codebase-explainer-agent/`, and `data/ingestion/`+`data/dbt/` keeps the PDW. **Do not rewrite the Go or Rust components into Python** (`spec2.md` §37).

**Recommended first integration milestone.** Stand up the unified Postgres (`data/warehouse/`), copy in the PDW dbt models, expose an `AnalyticsService` that reads `analytics.mart_*` tables, and build the first two read-only tools (`get_activity`, `get_project_activity`). This is the lowest-risk "Phase 1 + Phase 2 lite" combo: it gets a single high-value flow ("What did I work on this week?") end-to-end against the only project already at Phase 2 territory (`grace2.0`).

**Key risks (top 3).**

1. **Two incompatible vector stores already exist** — error-explainer hard-codes Qdrant (`internal/vector/store.go:23`); code-explain hard-codes sqlite-vec or LanceDB (`src/code_explain/store.py:190`). Phase 2 must standardize on pgvector (per `spec2.md` §10) and add adapters so history and codebase RAG share one store.
2. **LLM provider lock-in to local Ollama in all three LLM-touching projects.** error-explainer has a stdlib HTTP client with no abstraction (`internal/ollama/client.go:54`); webwatch shells out to a Python helper that calls `/api/generate` (`llm/summarize.py:51`); code-explain uses the `ollama` Python SDK (`src/code_explain/embedder.py:34`, `src/code_explain/llm.py:26`). Phase 4 needs the `LLMProvider` abstraction from `spec2.md` §15 *before* anything else LLM-related is added.
3. **No tests in two of the four projects** (webwatch: 0 tests, error-explainer: 6 files under `internal/` only, no `cmd/` or `main.go` tests). The PDW (22 pytest files + dbt tests) and code-explain (12 pytest files) are well-tested. Phase 1 must add at minimum a smoke test that wraps each project's CLI to prevent regressions during unification.

---

## 1. Project inventory

| # | Name | Path | Language | Purpose | Status |
|---|---|---|---|---|---|
| 1 | `error-explainer` | `/Users/gvleverett/Desktop/error-explainer` | Go 1.21+ (go.mod says 1.26.5) | Explain a pasted error/log/stack with a local LLM, with optional repo source extraction and prior-occurrence recall from a vector store. | **Usable, stable.** Single binary `explain-error`. No tests for `cmd/` or `main.go`. |
| 2 | `webwatch` (web-change-monitor) | `/Users/gvleverett/Desktop/web-change-monitor` | Go 1.26 + Python 3 stdlib | Track websites on a schedule, snapshot, diff, summarize change significance with a local LLM, post optional webhook. | **Usable, stable.** Zero tests anywhere in the repo. |
| 3 | `code-explain` (codebase-explainer-agent) | `/Users/gvleverett/Desktop/codebase-explainer-agent` | Python 3.10+ (Pipfile pins 3.14) | Index a codebase (tree-sitter AST chunks + embeddings + optional caller/callee graph), then ask questions, chat, or run a Stage-3 tool-calling agent that proposes patches. | **Usable, most mature.** 12 pytest modules; per-repo `.code-explain/` cache. |
| 4 | `grace2.0` (Personal Data Warehouse) | `/Users/gvleverett/Desktop/grace2.0` | Python 3.12 + SQL/dbt + Postgres 16 | Ingest personal activity (GitHub, Calendar, Gmail, Spotify) → raw Postgres → dbt marts → analytics. | **Usable at Phase 2 territory.** 22 pytest files + dbt tests. Dagster/FastAPI/Next.js deferred. |

---

## 2. Languages / frameworks

### 2.1 `error-explainer`

- **Language:** Go (go.mod:1 module path `github.com/gvleverett/error-explainer`)
- **Toolchain:** README states Go 1.21+; go.mod `go 1.26.5` — unusually high; verify before Phase 1
- **Primary framework:** `github.com/spf13/cobra v1.10.2` for the CLI; `github.com/charmbracelet/lipgloss v1.1.0` for terminal styling
- **Build:** `go build -o explain-error .`
- **Tests:** `go test ./...` — 6 files under `internal/`; no testify; stdlib `go testing`

### 2.2 `webwatch` (web-change-monitor)

- **Language:** Go 1.26 (go.mod) + Python 3 (stdlib only)
- **Primary frameworks:** Go side: `cobra v1.8.1`, `modernc.org/sqlite v1.29.6` (pure-Go SQLite, no CGO), `chromedp v0.16.0` (headless Chromium), `sergi/go-diff v1.3.1`, `golang.org/x/net/html`. Python side: none — `llm/summarize.py` uses only `urllib` + `json`.
- **Build:** `go build -o webwatch ./cmd/webwatch`
- **Tests:** **none** — `find -name '*_test.go'` is empty across the whole repo

### 2.3 `code-explain` (codebase-explainer-agent)

- **Language:** Python ≥3.10 (pyproject.toml `requires-python = ">=3.10"`); Pipfile pins 3.14
- **Primary frameworks:** Typer ≥0.12 (CLI), Rich ≥13.7 (terminal), `ollama` Python SDK ≥0.3 (LLM + embeddings), `tree-sitter` ≥0.23 + `tree-sitter-language-pack` ≥1.14 (AST parsing for 14 languages), `sqlite-vec` ≥0.1.9 (default vector store) or `lancedb` ≥0.10 (optional), `pathspec` ≥0.12 (gitignore)
- **Build:** `pip install -e .` (hatchling build backend); console script `code-explain = code_explain.cli:app`
- **Tests:** `pytest` (pyproject.toml:67 `testpaths=["tests"]`, `addopts="-q"`); 12 test modules under `tests/`

### 2.4 `grace2.0` (Personal Data Warehouse)

- **Language:** Python ≥3.12 (pyproject.toml) + SQL/dbt (dbt-core + dbt-postgres 1.9.0) + Postgres 16
- **Primary frameworks:** `uv` (Python package manager + venv), `click` ≥8.1 (CLI), `psycopg[binary]` ≥3.1.18 (Postgres driver), `httpx` ≥0.27 (HTTP client for connectors), `pydantic` ≥2.6 + `pydantic-settings` ≥2.2 (settings + models), `dbt-core`/`dbt-postgres` 1.9.0 (transformations)
- **Build:** `make dbt` (docker compose) + `make sync-*` / `make test` (ingestion)
- **Tests:** `make test` → `cd ingestion && uv run pytest -q` (22 pytest files); `dbt build` runs schema tests in `*_models.yml` + singular tests in `dbt/tests/`

---

## 3. Entry points

### 3.1 `error-explainer`

- **Binary:** `explain-error` (built via `go build -o explain-error .`)
- **Primary entry file:** `main.go` → `cmd.Execute()` (cobra root)
- **Console scripts:** `explain-error`
- **Launch behavior:** Single root cobra command (`cmd/root.go:84`). Resolves input from `-m <text>`, a file path positional, or piped stdin (capped 256KB) via `internal/input/input.go:41`. Detects TTY vs pipe for spinner/static output (`cmd/root.go:292`). Pipeline: input → `internal/analyze.Analyze` (lang detect, stack parse, log group) → optional `internal/repo` source extraction (`--repo`) → optional Qdrant history recall (`--no-history` to skip) → POST `/api/chat` to local Ollama → `internal/render.Parse` + `internal/render.Render` (lipgloss).

### 3.2 `webwatch` (web-change-monitor)

- **Binary:** `webwatch` (built via `go build -o webwatch ./cmd/webwatch`)
- **Primary entry file:** `cmd/webwatch/main.go`
- **Console scripts:** `webwatch`
- **Subcommands** (registered in `internal/cli/commands.go`): `add <url>`, `list`, `remove <id>`, `run`, `start` (scheduler daemon), `changes`, `config` (set `ollama_url`/`ollama_model`/`webhook_url`/`chrome_path` in `~/.webwatch/config.json`)
- **Launch behavior:** `webwatch start` runs the scheduler loop (`internal/scheduler/scheduler.go:26`, default 30s tick) until SIGINT/SIGTERM (handled at `internal/cli/signal.go:10`); each tick calls `Worker.CheckAll` (`internal/worker/worker.go:74`), which fetches/renders each due site, normalizes HTML, hashes, diffs, persists snapshots/changes, shells out to `python3 llm/summarize.py` to summarize+rate, and POSTs to webhook.

### 3.3 `code-explain` (codebase-explainer-agent)

- **Binary:** `code-explain` (console script in pyproject.toml: `code-explain = code_explain.cli:app`)
- **Primary entry file:** `code_explain/cli.py:127 main` (Typer app with `_FallbackGroup` so `code-explain <path>` is the hidden default that indexes-then-RPLs)
- **Console scripts:** `code-explain`
- **Subcommands** (defined in `src/code_explain/cli.py`): `index [PATH]`, `ask [PATH] QUESTION`, `chat [PATH]` (interactive), `graph [PATH]`, `agent [PATH] TASK`, `status [PATH]`, `reset [PATH]`, `config`
- **Launch behavior:** Default (`code-explain [PATH]`) indexes-if-stale via `code_explain/indexer.py` (two-tier staleness: mtime fast path + sha256 content path) then enters an interactive Rich REPL that calls `code_explain.ask.answer_question_stream` (`src/code_explain/ask.py:38`).

### 3.4 `grace2.0` (Personal Data Warehouse)

- **Binary:** `pdw` (console script `pdw = pdw.cli:main`)
- **Primary entry file:** `ingestion/src/pdw/cli.py:24 main` (Click group)
- **Console scripts:** `pdw`
- **Subcommands:** `migrate`, `seed`, `status`, `sync {github, github-issues, calendar, gmail, spotify}`, `auth {google, spotify}` (writes refresh tokens to `.env`)
- **Launch behavior:** Each `sync` reads cursor from `ops.sync_state` (`pdw/migrations/sql/0002_sync_state_entity.sql`), iterates paginated external API, normalizes into `pdw/models.py` dataclasses, upserts idempotently via `pdw/pipeline/loaders.py`, advances cursor, and writes one `ops.pipeline_runs` audit row. `dbt` is a separate `make dbt` invocation that runs `docker compose run --rm dbt build`.

---

## 4. APIs

### 4.1 `error-explainer`

**HTTP routes:** none exposed externally. Outbound HTTP only:

- `POST {OLLAMA_HOST}/api/chat` — `internal/ollama/client.go:54 Chat()`. Returns typed `ConnectionError` / `ModelNotFoundError`.
- `POST {OLLAMA_HOST}/api/embed` — `internal/ollama/client.go:101 Embed()`. Same error classification.
- `GET` then `PUT /collections/{name}` (Qdrant REST) — `internal/vector/qdrant.go:130 EnsureCollection()`. Cosine, dim=N.
- `POST /collections/{name}/points/search` — `internal/vector/qdrant.go:176 Search()`. Cosine search returning matches ≥ threshold with payloads.
- `GET /collections/{name}/points/{id}` — `internal/vector/qdrant.go:206 GetPoint()`. 404 → `(nil, nil)`.
- `PUT /collections/{name}/points?wait=true` — `internal/vector/qdrant.go:231 UpsertPoint()`. Idempotent upsert.
- `os/exec` to `git -C abs rev-parse --show-toplevel` — `internal/repo/repo.go:37 Find()`.
- `os/exec` to `git -C root grep -n -E --full-name pattern -- [pathspec]` — `internal/repo/repo.go:167 Grep()`.

**CLI:** one root cobra command with 13 flags (see §2 of the audit JSON). No subcommands.

**Internal callables that the OS tool layer should expose:**

- `internal/analyze.Analyze(text) *Context` — `analyze.go:58` — full pipeline; self-gating via `JSON() == ""`.
- `internal/analyze.DetectLanguage(text)` — `analyze.go:130` — Go/Python/Java/Rust/Ruby/Node/.NET/generic.
- `internal/analyze.ParseStack(text, lang)` — `analyze.go:176` — multi-language frame extractor, cap=25.
- `internal/analyze.GroupErrors(text)` — `analyze.go:323` — collapses near-duplicate log blocks; `Signature()` at `analyze.go:436` is the collision key.
- `internal/render.Parse(content) []Section` — `render.go:56` — splits model output on the five section markers (WHAT/PROBABLE/EVIDENCE/INVESTIGATE/FIXES), robust to markdown/list/case noise.
- `internal/history.ParseSummary(content)` — `history.go:158` — extracts machine-storable cause + fixes.
- `internal/repo.(*Repo).Resolve(path)` — `repo.go:74` — stack-frame → existing-file resolver (handles absolute, container-prefixed, module-path, unique-basename).
- `internal/repo.(*Repo).Grep(pattern, pathspec)` — `repo.go:167` — git grep wrapper returning `{File, Line, Text}`.
- `internal/source.Extract(r, ctx, contextLines)` — `source.go:55` — byte-capped (64KB) code windows around frames + function defs.
- `internal/ollama.Client` — `client.go:54 Chat` and `client.go:101 Embed` — stdlib Ollama HTTP client.
- `internal/vector.Store` — `store.go:23` — four-method vector-store interface (EnsureCollection/Search/GetPoint/UpsertPoint); `history.History` consumes it.
- `internal/prompt.System()` / `User()` — `prompt.go:22,71` — canonical system prompt + block assembler.
- `internal/input.Resolve(message, args)` — `input.go:41` — precedence-resolved input gatherer.
- `internal/history.History.Recall(ctx, embedText)` — `history.go:53` — embed → search → `[]Prior{Score, Count, LastSeen, Cause, Fixes}`.

### 4.2 `webwatch` (web-change-monitor)

**HTTP routes:** none exposed externally. Outbound:

- `POST {webhook_url}` — `internal/notify/notify.go:64 PostWebhook`. Best-effort JSON webhook poster; payload `{url, name, diff, summary, importance, occurred_at}`.
- `POST {ollama_url}/api/generate` — invoked from `llm/summarize.py:51` via Go subprocess wrapper `internal/llmclient/llmclient.go:36 Summarize`.

**CLI subcommands** (see §3.2). The CLI is the only public surface; the polyglot seam is the JSON-in/JSON-out `internal/llmclient` (`{before, after, diff, ollama_url, ollama_model}` → `{summary, importance}`).

**Internal callables to expose:**

- `internal/normalize.Text(htmlBytes)` — `normalize.go:29` — HTML → stable visible text.
- `internal/compare.Hash(content)` — `compare.go:14` — SHA-256 hex.
- `internal/compare.Diff(old, new)` — `compare.go:28` — compact unified-ish diff, collapses equal runs ≥5 lines.
- `internal/fetcher.Get(ctx, url)` — `fetcher.go:16` — redirect-safe HTTP fetch (30s timeout, 5MB cap).
- `internal/llmclient.Summarize` — `llmclient.go:36` — Go subprocess wrapper for the LLM step; the polyglot contract.
- `internal/notify.PostWebhook` — `notify.go:64` — best-effort JSON webhook poster.
- `llm/summarize.py` — Ollama provider, JSON-only response format, recovers from prose-wrapped JSON, classifies importance LOW/MEDIUM/HIGH. **System prompt at `llm/summarize.py:24` is the highest-value reuse target.**

### 4.3 `code-explain` (codebase-explainer-agent)

**HTTP routes:** none. CLI-only. Communication with Ollama happens over HTTP via the `ollama` Python SDK at `cfg.ollama_host` (default `http://localhost:11434`).

**CLI subcommands** (see §3.3).

**Python API surface** (callable via `import`, not over network — the OS tool layer must shell out to `code-explain ask` or import the package):

- `code_explain.config.Config.resolve` — `src/code_explain/config.py:68` — one-stop resolver (defaults → env → `.code-explain/config.json` → CLI).
- `code_explain.Embedder.embed_query` / `embed_batch` — `embedder.py:62, 74`.
- `code_explain.retriever.Retriever.retrieve` — `retriever.py:40` — full RAG pipeline (embed → vector+FTS5 RRF → optional LLM rerank → per-file cap → graph expansion → budget pack).
- `code_explain.retriever.Retriever.render_context` — `retriever.py:246` — citation-block renderer.
- `code_explain.llm.LLMClient.chat_stream` / `chat_turn` — `llm.py:34, 73` — streaming + tool-call turn modes.
- `code_explain.llm.LLMClient.supports_tools` — `llm.py:108` — cached probe of model's `tools` capability.
- `code_explain.discovery.discover_files` — `discovery.py:77` — file enumeration honoring `.gitignore` + `.codeexplainignore`.
- `code_explain.parser.parse_file` — `parser.py:230` — AST-aware chunking for 14 languages.
- `code_explain.graph.callers_of` / `callees_of` / `expand` — `graph.py:401, 406, 348`.
- `code_explain.ask.answer_question_stream` — `ask.py:38` — full RAG answer with path:line citations.
- `code_explain.errors.OllamaUnavailableError` / `raise_ollama_or_reraise` — `errors.py:12, 39`.
- `code_explain.prompts.SYSTEM_PROMPT` / `SYSTEM_PROMPT_GRAPH` / `SYSTEM_PROMPT_AGENT` / `CONTEXT_HEADER_TEMPLATE` — `prompts.py:5, 33, 43, 25`.

### 4.4 `grace2.0` (Personal Data Warehouse)

**HTTP routes:** none. No HTTP server. CLI + dbt only.

**Outbound HTTP** (all via `httpx` injectable client `pdw/connectors/base.py:51`):

- GitHub REST v3: `/user/repos`, `/repos/{o}/{r}/commits`, `/repos/{o}/{r}/issues` (`pdw/connectors/github.py`).
- Google Calendar v3: `/calendars/{id}/events` (`pdw/connectors/calendar.py`).
- Gmail v1: `/gmail/v1/users/me/messages` (metadata only) (`pdw/connectors/gmail.py`).
- Spotify Web API v1: `/v1/me/player/recently-played` + `https://accounts.spotify.com/api/token` (`pdw/connectors/spotify.py`).
- Google OAuth 2.0: `/token` (refresh) (`pdw/connectors/auth.py`).

**CLI subcommands** (see §3.4).

**Internal callables to expose:**

- `pdw.db.connect` — `ingestion/src/pdw/db.py:20` — context-managed psycopg.
- `pdw.config.get_settings` — `ingestion/src/pdw/config.py:76` — typed env-var access.
- `pdw.pipeline.runner.run_github` / `run_github_issues` / `run_calendar` / `run_gmail` / `run_spotify` — `ingestion/src/pdw/pipeline/runner.py:75, 151, 234, 275, 326` — return `RunSummary`.
- `pdw.synthetic.generate` — `ingestion/src/pdw/synthetic/generator.py:263` — deterministic synthetic dataset.
- `pdw.synthetic.categorize.categorize` — `ingestion/src/pdw/synthetic/categorize.py:73` — keyword calendar title categorizer.
- `pdw.connectors.auth.run_oauth_flow` / `run_spotify_oauth_flow` — `pdw/connectors/auth.py:142, 166` — generic + Spotify PKCE OAuth loops.
- `pdw.connectors.base.HttpClient` — `pdw/connectors/base.py:51` — injectable httpx wrapper with retry + typed error translation.

---

## 5. Databases

### 5.1 `error-explainer`

- **Engine:** Qdrant (external, soft dependency). No DSN env var per se; `EXPLAIN_VECTOR_HOST` (default `http://localhost:6333`).
- **Schema layout:** one collection (default `explain-errors`) with Cosine config sized to the embedding model dim (768 for `nomic-embed-text`). Point id = `FNV-64a(signature)` (`history.go:185`). Payload schema (`history.go:119-129`): `signature`, `representative`, `language`, `cause`, `fixes`, `model`, `count`, `first_seen`, `last_seen` (RFC3339).
- **Key collection:** `explain-errors` (configurable via `EXPLAIN_COLLECTION`).

### 5.2 `webwatch` (web-change-monitor)

- **Engine:** SQLite (pure-Go `modernc.org/sqlite v1.29.6`, no CGO; WAL mode; FK on).
- **DSN env var:** none — DB lives at `~/.webwatch/webwatch.db`; settings at `~/.webwatch/config.json`.
- **Schema layout** (3 tables, migrations applied idempotently at `internal/db/db.go:80`):
  - `websites(id, url UNIQUE, name, created_at, check_frequency_seconds, last_checked_at, next_check_at, last_status, last_error, render_js)`
  - `snapshots(id, website_id FK CASCADE, content_hash, content, created_at)` + index `(website_id, created_at)`
  - `changes(id, website_id FK CASCADE, old_snapshot_id FK SET NULL, new_snapshot_id FK CASCADE, diff, summary NULLABLE, importance, created_at)` + index `(website_id, created_at)`

### 5.3 `code-explain` (codebase-explainer-agent)

- **Engine:** SQLite (default) with `sqlite-vec` extension; optional `lancedb` (`--vector_backend` / `CODE_EXPLAIN_VECTOR_BACKEND`).
- **DSN env var:** none — `--db` CLI flag (default `<repo>/.code-explain/index.db`). `code_explain/store.py:198` swaps in `pysqlite3-binary` on macOS system Python for loadable-extension support.
- **Schema layout** (`src/code_explain/store.py:59 SCHEMA_SQL`, graph additions in `store.py:36 GRAPH_SCHEMA_SQL`):
  - `chunks(chunk_id PK, rel_path, lang, kind, symbol, parent_symbol, start/end_line/byte, text, n_tokens, file_hash, mtime, created_at)`
  - `files(rel_path PK, lang, file_hash, mtime, n_chunks, indexed_at)`
  - `meta(key, value)`
  - `chunk_vec` (sqlite-vec `vec0`, `FLOAT[<embed_dim>]`)
  - `chunks_fts` (FTS5 over `text/symbol/rel_path` with UNINDEXED `chunk_id`)
  - `edges(source_chunk_id, target_chunk_id, edge_kind, via_symbol, created_at)` — graph only
  - `imports(rel_path, symbol, alias, module_path, target_rel_path)` — graph only

### 5.4 `grace2.0` (Personal Data Warehouse)

- **Engine:** PostgreSQL 16 (single instance, containerized, `postgres:16-alpine`).
- **DSN env vars:** `DATABASE_URL` (host-run ingestion); dbt container uses `DBT_POSTGRES_HOST/USER/PASSWORD/PORT/DB/SCHEMA` (`docker-compose.yml:40-45`).
- **Schema layout:**
  - `public` — raw tables: `raw_github_repositories`, `raw_github_commits`, `raw_github_pull_requests`, `raw_github_issues`, `raw_calendar_events`, `raw_gmail_messages`, `raw_spotify_plays` + ops (`pipeline_runs`, `sync_state`, `schema_migrations`).
  - `analytics` — marts: `dim_date`, `dim_repository`, `fct_commits`, `fct_calendar_events`, `fct_pull_requests`, `fct_issues`, `fct_email_messages`, `fct_spotify_plays`, `mart_daily_activity`, `mart_project_activity`, `mart_monthly_summary`.
  - `staging` and `intermediate` — dbt schemas (views).
- **Key tables for the OS to read:** `mart_daily_activity`, `mart_monthly_summary`, `mart_project_activity`, `dim_date`, `dim_repository`, `fct_*`, `pipeline_runs`.

---

## 6. Dependencies

### 6.1 `error-explainer`

| Name | Version | Purpose |
|---|---|---|
| `github.com/spf13/cobra` | v1.10.2 | CLI framework |
| `github.com/charmbracelet/lipgloss` | v1.1.0 | Terminal color/styling |
| `github.com/aymanbagabas/go-osc52/v2` | v2.0.1 (indirect) | OSC52 clipboard for lipgloss |
| `github.com/charmbracelet/colorprofile` | v0.2.3 (indirect) | Terminal color detection |
| `github.com/charmbracelet/x/ansi` | v0.8.0 (indirect) | ANSI parsing for lipgloss |
| `github.com/charmbracelet/x/cellbuf` | v0.0.13 (indirect) | Cell-buffer primitives |
| `github.com/charmbracelet/x/term` | v0.2.1 (indirect) | Terminal capability detection |
| `github.com/inconshreveable/mousetrap` | v1.1.0 (indirect) | Windows "press any key" stub |
| `github.com/lucasb-eyer/go-colorful` | v1.2.0 (indirect) | Color-space conversion |
| `github.com/mattn/go-isatty` | v0.0.20 (indirect) | IsTTY detection (rolled-our-own at `cmd/root.go:292`) |
| `github.com/mattn/go-runewidth` | v0.0.16 (indirect) | East-Asian wide-char width |
| `github.com/muesli/termenv` | v0.16.0 (indirect) | Terminal environment queries |
| `github.com/rivo/uniseg` | v0.4.7 (indirect) | Unicode grapheme/word segmentation |
| `github.com/spf13/pflag` | v1.0.9 (indirect) | POSIX/GNU flag parser |
| `github.com/xo/terminfo` | v0.0.0-20220910 (indirect) | Terminfo parser |
| `golang.org/x/sys` | v0.30.0 (indirect) | Low-level OS syscalls |

### 6.2 `webwatch` (web-change-monitor)

| Name | Version | Purpose |
|---|---|---|
| `github.com/sergi/go-diff/diffmatchpatch` | v1.3.1 | Line-level unified-ish diff (`internal/compare/compare.go:32`) |
| `github.com/spf13/cobra` | **v1.8.1** | CLI command tree |
| `golang.org/x/net/html` | v0.27.0 | HTML tokenizer (`internal/normalize/normalize.go:30`) |
| `modernc.org/sqlite` | v1.29.6 | Pure-Go SQLite (no CGO); registered as `"sqlite"` at `internal/db/db.go:11` |
| `github.com/chromedp/chromedp` | v0.16.0 | Headless Chromium (`internal/render/render.go:13`) |
| Python 3 stdlib (`urllib`, `json`) | n/a | Ollama HTTP client in `llm/summarize.py`; **no third-party deps** (`llm/requirements.txt` is empty) |

### 6.3 `code-explain` (codebase-explainer-agent)

| Name | Version | Purpose |
|---|---|---|
| `typer` | ≥0.12 | CLI framework with `_FallbackGroup` (`src/code_explain/cli.py:43`) |
| `rich` | ≥13.7 | Terminal rendering (Markdown streaming, panels, tables) |
| `ollama` | ≥0.3 | Local LLM + embedding client (`embedder.py:34`, `llm.py:26`) |
| `tree-sitter` | ≥0.23 | AST parsing core |
| `tree-sitter-language-pack` | ≥1.14 | Prebuilt grammars for 14 languages |
| `sqlite-vec` | ≥0.1.9 | SQLite vector extension (`store.py:190`) |
| `pathspec` | ≥0.12 | Gitignore pattern matcher (`discovery.py:199`) |
| `pysqlite3-binary` | ≥0.5 (optional, `macos-system-python`) | Shim sqlite3 for loadable-extension support |
| `lancedb` | ≥0.10 (optional, `lancedb`) | Alternative vector backend |
| `pytest` | ≥8.0 (dev) | Test runner |
| `pytest-mock` | ≥3.12 (dev) | Mocking fixture |

### 6.4 `grace2.0` (Personal Data Warehouse)

| Name | Version | Purpose |
|---|---|---|
| `psycopg[binary]` | ≥3.1.18 | Postgres driver (sync) |
| `pydantic` | ≥2.6 | Data modeling |
| `pydantic-settings` | ≥2.2 | Typed env-var loading |
| `click` | ≥8.1 | Builds the `pdw` CLI |
| `httpx` | ≥0.27 | HTTP client used by all connectors (injectable in tests) |
| `dbt-core` + `dbt-postgres` | 1.9.0 | SQL transforms (`ghcr.io/dbt-labs/dbt-postgres:1.9.0`) |
| `uv` | system | Python package manager + venv (hatchling backend) |
| `postgres:16-alpine` | n/a | Warehouse storage |
| Docker / Docker Compose | v2 plugin | Local stack orchestration |
| `pytest` | ≥8.0 | Test runner |
| `ruff` | ≥0.4 | Linting |

### 6.5 Duplicates across projects

The four projects have **minimal direct dependency duplication** because three of them are in different languages (Go × 3, Python × 1, mixed Go+Python × 1). The cross-cutting concerns that *do* appear in multiple places are documented under §9.

The two Go projects that share `github.com/spf13/cobra` (`error-explainer` v1.10.2 vs `webwatch` v1.8.1) are independent — they will both be invoked as subprocesses from the OS, not linked into a single binary, so version divergence is irrelevant. The same logic applies to indirect dependency divergence between the Go projects.

---

## 7. Existing service boundaries

### 7.1 `error-explainer`

| Package | Responsibility |
|---|---|
| `cmd/` | cobra root command, flag/env binding, spinner, orchestration of input → analyze → source → history → ollama → render |
| `internal/input` | `Resolve()`: gather text from `-m`, file path, or piped stdin (256KB cap + truncation flag) |
| `internal/analyze` | Pure (no I/O) text analysis: `DetectLanguage`, `ParseStack` (Go/Python/Java/Node/Ruby/Rust/.NET/generic), `GroupErrors` (log block dedup with signature normalization), `Signature` (deterministic family key) |
| `internal/repo` | Minimal git integration: `Find` repo root, `Resolve` stack-frame paths, `ReadFileLines`, `Grep` for symbol definitions |
| `internal/source` | `Extract` relevant source snippets; byte-capped (64KB) and file-capped (5); `Format` for line-numbered blocks |
| `internal/ollama` | stdlib HTTP client to Ollama: `Chat` (`/api/chat`) + `Embed` (`/api/embed`); typed `ConnectionError` / `ModelNotFoundError` |
| `internal/vector` | `Store` interface + `QdrantClient` over `net/http`; `ErrUnreachable` + `ErrDimMismatch` for graceful degradation |
| `internal/history` | Orchestrator: `Recall` (embed → EnsureCollection → Search) and `Record` (FNV-64a id, count+last_seen upsert); `EmbedText`, `ParseSummary`, `FormatBlock` |
| `internal/prompt` | `System()` returns the five-section instructions; `User()` assembles origin note + PARSED CONTEXT + RELEVANT SOURCE + PRIOR OCCURRENCES + raw input |
| `internal/render` | `Parse()` splits model output on five section markers; `Render()` colorizes via lipgloss; falls back to a neutral heading when no markers found |

**Boundary quality:** excellent. The orchestrator at `cmd/root.go` is the only place with side effects; every other package is a pure function or a thin IO wrapper. Soft degradation (`--no-history`, `--no-repo`, capped sizes) is a first-class design pattern — history/source never abort the run.

### 7.2 `webwatch` (web-change-monitor)

| Package | Responsibility |
|---|---|
| `internal/cli` | cobra root + 7 subcommands and SIGINT/SIGTERM handler (`internal/cli/signal.go:10`) |
| `internal/config` | `~/.webwatch` path resolution + JSON-backed `Settings` (OllamaURL/OllamaModel/WebhookURL/ChromePath); `Load`/`Save` |
| `internal/db` | SQLite open/migrate + queries for `websites`, `snapshots`, `changes` |
| `internal/fetcher` | Plain HTTP GET (30s timeout, 10 redirects, 5MB cap, UA `webwatch/0.1`) |
| `internal/render` | chromedp-based headless Chromium render with 2s post-load settle; shared browser; `Close()` to release |
| `internal/normalize` | `Text(htmlBytes)` strips script/style/nav/header/footer/svg/form/iframe/noscript; collapses whitespace |
| `internal/compare` | `Hash` (sha256 hex) + `Diff` (compact unified-ish, hides equal runs >5 lines) — pure |
| `internal/llmclient` | Spawns `python3 llm/summarize.py`, JSON in/JSON out, 3-min default timeout — the polyglot seam |
| `internal/worker` | Orchestrates fetch/render → normalize → hash → diff → summarize → persist → notify |
| `internal/scheduler` | Tick loop (default 30s) calling `Worker.CheckAll`; runs until ctx cancelled |
| `internal/notify` | Renders the `🚨 CHANGE DETECTED` block and POSTs the event to a configured webhook |
| `llm/summarize.py` | Ollama provider; strict-JSON system prompt; `{summary, importance}` |

**Boundary quality:** good. Polyglot seam (`internal/llmclient` ↔ `llm/summarize.py`) is intentionally narrow — a JSON contract that can be swapped to an HTTP microservice later.

### 7.3 `code-explain` (codebase-explainer-agent)

| Module | Responsibility |
|---|---|
| `code_explain.discovery` | `discover_files`: git ls-files → walk + pathspec gitignore (`discovery.py:77`) |
| `code_explain.parser` | `parse_file`: tree-sitter AST chunking for 14 languages with line-based fallback |
| `code_explain.chunker` | `Chunk` dataclass; `estimate_tokens`, `file_sha256`, `new_chunk_id`, `line_chunk`, `module_chunk` |
| `code_explain.embedder` | `Embedder`: Ollama embedding client; `embed_query`, `embed_batch` with num_ctx-safe options |
| `code_explain.store` | `VectorStore` Protocol, `SQLiteVecStore`: FTS5 + sqlite-vec; graph + hybrid FTS query directly on the SQLite conn |
| `code_explain.lancedb_store` | `LanceDBStore`: optional LanceDB backend with SQLite sidecar; graph + FTS no-op when active |
| `code_explain.indexer` | Orchestrates discover → parse → chunk → embed → upsert with two-tier staleness (mtime fast path + sha256 content path); backend factory |
| `code_explain.retriever` | `Retriever`: query → embed → vector+FTS5 RRF → optional LLM rerank → per-file cap → graph expansion → token-budget pack → `render_context` |
| `code_explain.reranker` | `Reranker` Protocol, `OllamaReranker`: lazy LLM rerank of top 20; falls back to original order on error |
| `code_explain.graph` | `build_graph`, `expand`, `callees_of`, `callers_of`: caller/callee/contains edges from existing chunks (no re-parse); BFS expand |
| `code_explain.llm` | `LLMClient`: streaming `chat_stream` + non-streaming `chat_turn` with tools; `supports_tools` probe caches `ollama.show()` |
| `code_explain.ask` | `answer_question_stream` (one-shot RAG answer) + `chat_loop` (interactive REPL); Markdown streaming |
| `code_explain.agent` | Stage-3 tool-dispatch loop: read_file / list_symbols / find_callers / search_code / propose_patch / run_tests; `--apply` gate |
| `code_explain.prompts` | Only place prompt text lives (`SYSTEM_PROMPT`, `SYSTEM_PROMPT_GRAPH`, `SYSTEM_PROMPT_AGENT`, `CONTEXT_HEADER_TEMPLATE`) |
| `code_explain.errors` | `OllamaUnavailableError` + `raise_ollama_or_reraise` to translate httpx/ollama errors |
| `code_explain.config` | `Config`: defaults → env → `.code-explain/config.json` → CLI overrides; validated on resolve |
| `code_explain.cli` | Typer app with `_FallbackGroup`; subcommand dispatch (`index`, `ask`, `chat`, `graph`, `agent`, `status`, `reset`, `config`) |

**Boundary quality:** excellent. Each module owns one concern; the `Chunk` dataclass is the shared currency; prompts live in exactly one module; errors are translated in exactly one helper.

### 7.4 `grace2.0` (Personal Data Warehouse)

| Module | Responsibility |
|---|---|
| `pdw/connectors/base.py` | Connector primitives: `HttpClient` (httpx wrapper, typed errors), exception hierarchy |
| `pdw/connectors/auth.py` | One-time OAuth loops: Google (authorization-code + PKCE, port 8787) + Spotify (PKCE no-secret, port 8788) |
| `pdw/connectors/github.py` | GitHub REST v3 client + connector (repos, commits, PRs, issues — every PR is an issue; split on `pull_request` key) |
| `pdw/connectors/calendar.py` | Google Calendar v3 client + connector |
| `pdw/connectors/gmail.py` | Gmail v1 client + connector (metadata only) |
| `pdw/connectors/spotify.py` | Spotify Web API client + connector |
| `pdw/models.py` | Normalized record dataclasses (Repo, Commit, CalendarEvent, PullRequest, Issue, Email, TrackPlay) |
| `pdw/db.py` | psycopg connection helper: `connect()` context manager (commit on success / rollback on error) |
| `pdw/config.py` | pydantic-settings `Settings` class; loaded from repo-root `.env` |
| `pdw/migrations/runner.py` | Idempotent SQL migration runner; lexical discovery; `schema_migrations` bookkeeping |
| `pdw/migrations/sql/0001_init.sql` | `raw_github_repositories`, `raw_github_commits`, `raw_calendar_events` + `pipeline_runs` + `sync_state` |
| `pdw/migrations/sql/0002_sync_state_entity.sql` | Composite PK `(connector, entity_key)` on `sync_state` for per-entity cursors |
| `pdw/migrations/sql/0003_github_prs_issues.sql` | `raw_github_pull_requests` + `raw_github_issues` |
| `pdw/migrations/sql/0004_gmail.sql` | `raw_gmail_messages` (metadata only, date index) |
| `pdw/migrations/sql/0005_spotify.sql` | `raw_spotify_plays` (`source_id = "{track_id}:{played_at}"`) |
| `pdw/pipeline/loaders.py` | Source-agnostic idempotent upserts (`xmax=0` trick) + `RunSummary` + `record_run` + `upsert_sync_state` |
| `pdw/pipeline/checkpoints.py` | Per-entity cursor read/write helpers around `sync_state` |
| `pdw/pipeline/runner.py` | Per-source orchestrators (`run_github`, `run_github_issues`, `run_calendar`, `run_gmail`, `run_spotify`) |
| `pdw/synthetic/generator.py` | Deterministic (seed=42, anchor=now) synthetic dataset |
| `pdw/synthetic/categorize.py` | Keyword-rules calendar title categorizer (work/meeting/learning/personal/other) |
| `pdw/synthetic/loader.py` | Thin wrapper that loads `SyntheticDataset` into raw tables as `source='synthetic'` |
| `pdw/cli.py` | Click subcommand tree |
| `dbt/models/staging/*` | Views renaming/casting/standardizing raw tables; surrogate keys via `surrogate_key` macro |
| `dbt/models/intermediate/*` | `int_daily_activity`, `int_calendar_activity`, `int_project_activity` |
| `dbt/models/marts/*` | `dim_date`, `dim_repository`, `fct_*`, `mart_daily_activity`, `mart_monthly_summary`, `mart_project_activity` |
| `dbt/macros/*` | `surrogate_key.sql` (md5 concat), `generate_schema_name.sql` (staging → staging, intermediate → intermediate, marts → analytics) |
| `dbt/tests/*` | `commit_timestamp_plausible.sql`, `no_negative_durations.sql` |

**Boundary quality:** very good. The four-layer architecture (External APIs → Ingestion → Raw Postgres → dbt → Analytics → Presentation) is strictly observed; only `postgres` is long-running, `dbt` runs on demand via `make dbt`.

---

## 8. Reusable modules

The OS tool layer will call into each project at the entry points listed below. **Citations are `file:line`** so the Phase 1 implementer can jump straight to the function.

### 8.1 `error-explainer` → `ErrorService`

| Symbol | File:line | Why the OS wants it |
|---|---|---|
| `Analyze(text) *Context` | `internal/analyze/analyze.go:58` | Multi-language error/log/stack analyzer; `JSON() == ""` self-gates "nothing useful found" |
| `DetectLanguage(text) Language` | `internal/analyze/analyze.go:130` | Pure language detector with Go > Python > Java > Rust > Ruby > Node > .NET > generic priority tie-break |
| `ParseStack(text, lang) []Frame` | `internal/analyze/analyze.go:176` | Frame extractor for 7 languages + generic `file:line` fallback (cap 25) |
| `GroupErrors(text) []ErrorGroup` | `internal/analyze/analyze.go:323` | Collapses near-duplicate log blocks via normalization (strips timestamps/hex/PIDs/goroutine ids/file:line) |
| `Signature(text)` | `internal/analyze/analyze.go:436` | Deterministic collision key for an error family |
| `Parse(content) []Section` | `internal/render/render.go:56` | Splits model output on the 5 section markers (WHAT/PROBABLE/EVIDENCE/INVESTIGATE/FIXES); robust to markdown/list/case |
| `ParseSummary(content)` | `internal/history/history.go:158` | Extracts machine-storable PROBABLE CAUSE + POTENTIAL FIXES (each ≤1000 chars) |
| `EmbedText(ctx, raw)` | `internal/history/history.go:174` | Picks the embed-time representative (top error group, else first 4KB) |
| `(*Repo).Resolve(path)` | `internal/repo/repo.go:74` | Stack-frame → existing-file resolver (handles absolute, container-prefixed, module-path, unique-basename) |
| `(*Repo).Grep(pattern, pathspec)` | `internal/repo/repo.go:167` | `git grep -n -E --full-name` wrapper → `{File, Line, Text}` |
| `Extract(r, ctx, contextLines) Result` | `internal/source/source.go:55` | Byte-capped (64KB / 5 files / 8 frames) code windows around frames + function defs |
| `(*Client).Chat(ctx, model, []Message)` | `internal/ollama/client.go:54` | stdlib Ollama `/api/chat`; typed `ConnectionError` / `ModelNotFoundError` |
| `(*Client).Embed(ctx, model, input)` | `internal/ollama/client.go:101` | stdlib Ollama `/api/embed` |
| `Store` interface | `internal/vector/store.go:23` | 4-method vector-store abstraction (EnsureCollection/Search/GetPoint/UpsertPoint) |
| `System()` | `internal/prompt/prompt.go:22` | Canonical five-section system prompt |
| `User(text, origin, truncated, contextBlock, sourceBlock, priorBlock)` | `internal/prompt/prompt.go:71` | Block-assembler for the user message |
| `Resolve(message, args)` | `internal/input/input.go:41` | Precedence-resolved input gathering with 256KB cap |
| `(*History).Recall(ctx, embedText) []Prior` | `internal/history/history.go:53` | Embed → Search → `[]Prior{Score, Count, LastSeen, Cause, Fixes}` |

### 8.2 `webwatch` (web-change-monitor) → `MonitoringService`

| Symbol | File:line | Why the OS wants it |
|---|---|---|
| `Text(htmlBytes) string` | `internal/normalize/normalize.go:29` | HTML → stable visible text (strips boilerplate) |
| `Hash(content) string` | `internal/compare/compare.go:14` | SHA-256 hex of normalized text — cheap equality check |
| `Diff(old, new) string` | `internal/compare/compare.go:28` | Compact unified-ish diff, collapses equal runs ≥5 lines |
| `Get(ctx, url)` | `internal/fetcher/fetcher.go:16` | Redirect-safe HTTP fetch (30s timeout, 5MB cap, UA) |
| `Summarize(...)` | `internal/llmclient/llmclient.go:36` | Go subprocess wrapper around `llm/summarize.py`; Request struct is the polyglot contract |
| `llm/summarize.py` | `llm/summarize.py:24,51,72` | The "summarize a textual delta and rate it" pipeline; **system prompt and importance rubric are the reusable parts** |
| `PostWebhook(webhookURL, c)` | `internal/notify/notify.go:64` | Best-effort JSON webhook poster |

### 8.3 `code-explain` (codebase-explainer-agent) → `DeveloperService`

| Symbol | File:line | Why the OS wants it |
|---|---|---|
| `discover_files(...)` | `src/code_explain/discovery.py:77` | Gitignore-aware file enumeration |
| `parse_file(...)` | `src/code_explain/parser.py:230` | Tree-sitter AST chunking for 14 languages |
| `estimate_tokens(...)` | `src/code_explain/chunker.py:77` | Cheap 4-chars-per-token heuristic |
| `Embedder.embed_query / embed_batch` | `src/code_explain/embedder.py:62,74` | Ollama embedding client with num_ctx-safe options |
| `Retriever.retrieve(...)` | `src/code_explain/retriever.py:40` | Full RAG pipeline (embed → vector+FTS5 RRF → optional LLM rerank → per-file cap → graph expansion → budget pack) |
| `Retriever.render_context(...)` | `src/code_explain/retriever.py:246` | Citation-block renderer (FILE/path/Lstart-end (kind: symbol) headers) |
| `Config.resolve(...)` | `src/code_explain/config.py:68` | One-stop config resolver (defaults → env → `.code-explain/config.json` → CLI) |
| `LLMClient.chat_stream / chat_turn` | `src/code_explain/llm.py:34,73` | Ollama chat with streaming + tool-call turn modes |
| `LLMClient.supports_tools(...)` | `src/code_explain/llm.py:108` | Cached capability probe for the configured model |
| `graph.callers_of / callees_of / expand` | `src/code_explain/graph.py:401,406,348` | Caller/callee traversal + BFS over the edges table |
| `answer_question_stream(...)` | `src/code_explain/ask.py:38` | Full RAG answer pipeline with path:line citations |
| `SYSTEM_PROMPT*` and `CONTEXT_HEADER_TEMPLATE` | `src/code_explain/prompts.py:5,33,43,25` | Canonical prompts — reuse verbatim across projects |
| `Chunk` | `src/code_explain/chunker.py:27` | Shared currency data model |
| `OllamaUnavailableError` / `raise_ollama_or_reraise` | `src/code_explain/errors.py:12,39` | Uniform translation of httpx/ollama errors |

### 8.4 `grace2.0` (Personal Data Warehouse) → `AnalyticsService`

| Symbol | File:line | Why the OS wants it |
|---|---|---|
| `pdw.db.connect(...)` | `ingestion/src/pdw/db.py:20` | Context-managed psycopg |
| `pdw.config.get_settings(...)` | `ingestion/src/pdw/config.py:76` | Typed env-var access (DATABASE_URL + connector creds) |
| `pdw.pipeline.runner.run_github` | `ingestion/src/pdw/pipeline/runner.py:75` | Programmatic GitHub sync; returns `RunSummary` |
| `pdw.pipeline.runner.run_github_issues` | `ingestion/src/pdw/pipeline/runner.py:151` | Programmatic GitHub PR + issue sync |
| `pdw.pipeline.runner.run_calendar` | `ingestion/src/pdw/pipeline/runner.py:234` | Programmatic Google Calendar sync |
| `pdw.pipeline.runner.run_gmail` | `ingestion/src/pdw/pipeline/runner.py:275` | Programmatic Gmail metadata sync |
| `pdw.pipeline.runner.run_spotify` | `ingestion/src/pdw/pipeline/runner.py:326` | Programmatic Spotify recently-played sync |
| `pdw.synthetic.generate(...)` | `ingestion/src/pdw/synthetic/generator.py:263` | Deterministic synthetic dataset (seed=42) |
| `pdw.synthetic.categorize.categorize(...)` | `ingestion/src/pdw/synthetic/categorize.py:73` | Keyword-rule calendar title categorizer |
| `pdw.connectors.auth.run_oauth_flow` | `ingestion/src/pdw/connectors/auth.py:142` | Generic Google OAuth loop |
| `pdw.connectors.auth.run_spotify_oauth_flow` | `ingestion/src/pdw/connectors/auth.py:166` | Spotify PKCE OAuth loop |
| `pdw.connectors.base.HttpClient` | `ingestion/src/pdw/connectors/base.py:51` | Injectable httpx wrapper with retry + typed errors |
| `analytics.mart_daily_activity` | `dbt/models/marts/mart_daily_activity.sql` | Zero-filled daily activity for chart continuity |
| `analytics.mart_monthly_summary` | `dbt/models/marts/mart_monthly_summary.sql` | Month-over-month commits + active_repos + meeting minutes + active_days |
| `analytics.mart_project_activity` | `dbt/models/marts/mart_project_activity.sql` | Per-project activity + status (active/stale/inactive) |
| `analytics.dim_repository`, `analytics.fct_*` | `dbt/models/marts/*.sql` | Dimensions and facts |
| `public.raw_*.raw_payload` (JSONB) | `pdw/migrations/sql/*.sql` | Original payloads preserved as JSONB |
| `ops.pipeline_runs` | `pdw/migrations/sql/0001_init.sql:68` | Audit log of recent syncs |

---

## 9. Duplicate functionality

The four projects are mostly orthogonal because three of them are in different languages (Go × 2, Python × 1, mixed). What *does* duplicate is **conceptual** rather than code-level, and the OS should standardize once and reuse everywhere.

| Concept | Where it appears | Verdict |
|---|---|---|
| **HTTP client** | error-explainer: stdlib `net/http` in `internal/ollama/client.go:54` and `internal/vector/qdrant.go`; webwatch: stdlib `net/http` in `internal/fetcher/fetcher.go:16`; code-explain: `httpx` indirectly via `ollama` SDK + the project pins no `httpx` itself; grace2.0: `httpx>=0.27` (`pdw/connectors/base.py:51`) | **Conceptually similar, not near-identical.** error-explainer and webwatch use stdlib; grace2.0 uses `httpx`. Phase 1 can leave the existing clients in place; the OS's Python services should use `httpx` everywhere for consistency. |
| **LLM client (Ollama)** | error-explainer: stdlib HTTP at `internal/ollama/client.go:54` (no provider abstraction); webwatch: shells out to `python3 llm/summarize.py:51` which uses `urllib`; code-explain: `ollama>=0.3` Python SDK at `src/code_explain/llm.py:26` + `src/code_explain/embedder.py:34` | **Three different mechanisms for the same provider.** Phase 4 must introduce the `LLMProvider` abstraction from `spec2.md` §15 before any new LLM call is added. **Reuse opportunity:** `code_explain.llm.LLMClient.chat_stream` / `chat_turn` is the most complete of the three and already supports tool calling. |
| **Embedding client** | error-explainer: stdlib HTTP `Embed()` at `internal/ollama/client.go:101`; code-explain: `Embedder.embed_query / embed_batch` at `src/code_explain/embedder.py:62,74` (uses `ollama` SDK with num_ctx-safe options); webwatch: no embeddings; grace2.0: no embeddings today | **Two implementations.** Phase 2 should standardize on the `Embedder`-shaped interface (returns `[]float64` with model + dim tracked) and route through one `LLMProvider.embed()`. |
| **Vector store** | error-explainer: Qdrant REST at `internal/vector/store.go:23`; code-explain: sqlite-vec (default) or LanceDB at `src/code_explain/store.py:190` / `src/code_explain/lancedb_store.py:75` | **Hard incompatibility.** Phase 2 must standardize on **pgvector** per `spec2.md` §10 and adapt both projects (the `Store` interface in `internal/vector/store.go:23` is small enough to reimplement against `psycopg` + `pgvector`). |
| **Config loader** | error-explainer: env vars via `os.Getenv` in `cmd/root.go` (no central loader); webwatch: JSON at `~/.webwatch/config.json` (`internal/config/config.go:61`); code-explain: `Config.resolve` at `src/code_explain/config.py:68` (defaults → env → `.code-explain/config.json` → CLI); grace2.0: `pydantic-settings` at `ingestion/src/pdw/config.py:76` | **Three patterns.** The OS should use `pydantic-settings` (grace2.0's pattern) for everything Python and keep env-var-only config for the Go services. Do not retrofit the Go services to JSON. |
| **CLI framework** | error-explainer & webwatch: cobra (Go); code-explain: Typer (Python); grace2.0: Click (Python); the new `pdo` CLI per `spec2.md` §40: Typer | **By language, not redundant.** The two Python CLIs (grace2.0's `pdw` Click, code-explain's Typer) will both be wrapped by the new `pdo` Typer CLI in Phase 5; the Go CLIs stay subprocesses. |
| **OAuth refresh** | grace2.0: `pdw/connectors/auth.py` (Google + Spotify PKCE loops on port 8787/8788); error-explainer, webwatch, code-explain: no OAuth | **Single implementation, sufficient.** The OS can call `run_oauth_flow` / `run_spotify_oauth_flow` directly when it needs to onboard a new user. |
| **CLI flag → env precedence** | error-explainer: env-or-flag in `cmd/root.go`; code-explain: `Config.resolve`; grace2.0: `pydantic-settings`; webwatch: JSON config only (no env) | **Two patterns, both fine.** Consolidate the Python pattern in `pdo` via `pydantic-settings`. |
| **Logging / structured output** | All four have ad-hoc logging. None uses a structured logger. | **Build once in the OS** — the Phase 1 unification layer should adopt `structlog` (Python) and `log/slog` (Go) so every service emits the same `assistant.tool_call` events. |
| **HTML stripping** | webwatch: `internal/normalize/normalize.go:29`; error-explainer & code-explain: none; grace2.0: none | **Single implementation.** Reuse `internal/normalize.Text` via subprocess or reimplement in Python when needed. |

**Bottom line:** nothing is near-identical at the code level; the OS's job is to standardize the *concepts* (LLMProvider, Embedder, VectorStore, Config, Logger) and let each existing implementation satisfy the contract.

---

## 10. Integration risks

### 10.1 `error-explainer`

- **Go toolchain version:** go.mod declares `go 1.26.5`; README says 1.21+. **Verify the actual CI version before Phase 1** — pulling `go 1.26.5` may not work on every dev machine.
- **Ollama must be reachable:** `internal/ollama/client.go:54` will hang/fail without a local Ollama. The `ConnectionError` is typed (`errors.As`), so the OS should map it to a friendly tool result.
- **Qdrant is a soft dependency, but Phase 2 will rip it out.** The `Store` interface at `internal/vector/store.go:23` is the only thing history depends on — reimplement against pgvector.
- **Cosmetic dependency chain via lipgloss pulls 11 indirect Go modules.** None affect the OS, but build reproducibility requires a vendor or a `go.sum` policy.
- **No `cmd/` tests.** Adding even one smoke test that calls `cmd.Execute()` with a mocked stdin would catch regressions during Phase 1.

### 10.2 `webwatch` (web-change-monitor)

- **Zero tests.** Highest regression risk of all four projects during unification.
- **Chromedp requires Chrome/Chromium.** `chrome_path` is configurable, but the OS scheduler will need a Docker image that bundles Chromium.
- **Polyglot seam:** `internal/llmclient/llmclient.go:36` shells out to `python3 llm/summarize.py`. The OS must preserve a `python3` in the runtime environment (or replace this seam with an HTTP call to a Python microservice).
- **Settings are JSON, not env vars.** `internal/config/config.go:14-17` only reads `~/.webwatch/config.json`. Phase 1 must either keep the JSON file or wrap it with an env-var override layer.
- **Pure-Go SQLite works, but the file lives at `~/.webwatch/webwatch.db` per-user.** Decide early whether the OS uses one shared DB or per-user.

### 10.3 `code-explain` (codebase-explainer-agent)

- **macOS Python + sqlite-vec requires the `pysqlite3-binary` shim** (`src/code_explain/store.py:198`). If the OS uses a different Python build (e.g., `uv`-managed), confirm sqlite-vec loads.
- **Embedding model dim is fixed at index-build time.** Changing `CODE_EXPLAIN_EMBED_DIM` (default 768) forces a full re-index (`Config.validate`). The OS's pgvector migration must preserve this invariant.
- **Pipfile is empty** and pins Python 3.14 — devs may need `pip install -e .[dev]` directly. Phase 1 should consolidate deps into the parent repo's `pyproject.toml`.
- **`code-explain agent` can propose and apply patches via `git apply`** (`src/code_explain/agent.py:316`). This is a WRITE/DESTRUCTIVE-class tool; the OS must wrap it behind Phase 6's confirmation model before exposing it.
- **Per-repo `.code-explain/` cache.** The OS either (a) keeps one cache per project or (b) builds a cross-project index. (a) is simpler and respects the existing design.

### 10.4 `grace2.0` (Personal Data Warehouse)

- **PostgreSQL 16 only.** No fallback to 14/15; dbt container pins `ghcr.io/dbt-labs/dbt-postgres:1.9.0`. Phase 2 must add pgvector to this Postgres image (e.g., `pgvector/pgvector:pg16`).
- **dbt runs in a container, ingestion on the host.** Both connect to the same Postgres via `DATABASE_URL` vs `DBT_POSTGRES_*`. The OS must keep this split or unify in a single compose network.
- **OAuth scopes already reserved but unused:** `SPREADSHEETS_READONLY_SCOPE` and `GOOGLE_SCOPES` at `pdw/connectors/auth.py:24,31`. Don't double-reserve when adding the assistant.
- **`sync_state` PK is `(connector, entity_key)`** (`pdw/migrations/sql/0002_sync_state_entity.sql`). The OS's tool-execution audit (`spec2.md` §24) is a different concern — keep them separate.
- **Synthetic data generator is deterministic but only covers the 6 existing connectors.** A new connector (e.g., notes) needs both a synthetic generator and a real connector — build them together.

### 10.5 Cross-cutting risks

- **No unified `.env` schema.** Each project reads what it needs; the parent repo's `.env.example` (per `spec2.md` §39) must enumerate every variable from the Appendix below.
- **Three different logging conventions.** Phase 1 should pick one (`structlog` + `log/slog`) and emit JSON.
- **No health checks anywhere.** The OS's scheduler/orchestrator needs a `pdo health` command — add per-service `/health` (or `--health`) probes in Phase 1.
- **No shared secrets manager.** All tokens live in `.env` (grace2.0) or `~/.webwatch/config.json` (webwatch). Post-MVP, consider OS keychain integration.

---

## 11. Recommended unified architecture

This maps the four projects to `spec2.md` §3 (USER → Interface → Assistant/Agent → Tools → Services → Storage/External).

### 11.1 Mapping to §3

| §3 Role | Filled by | Notes |
|---|---|---|
| **USER** | The human | — |
| **Interface** (CLI / Web / API) | New `apps/cli` (Typer `pdo` CLI per `spec2.md` §40), new `apps/api` (FastAPI per `spec2.md` §33), future `apps/web` (per `spec2.md` §34) | Phase 5: CLI; Phase 6: API + Web |
| **Assistant / Agent** | New `agent/agent.py`, `agent/planner.py`, `agent/tools/`, `agent/prompts/`, `agent/memory/` | Phase 3-4 |
| **Tools** | New `agent/tools/` registry — initial read-only tools per `spec2.md` §11 | Phase 3 |
| **Domain Services** | `services/knowledge/`, `services/developer/`, `services/errors/`, `services/monitoring/`, `services/analytics/` | Phase 1; each wraps one or two existing projects |
| **Storage** | Unified Postgres + pgvector under `storage/postgres/` + `storage/vector/` | Phase 2 |
| **External** | Existing connectors (grace2.0), existing OAuth flows, Ollama, Qdrant (transitional), GitHub/Calendar/Gmail/Spotify APIs | Preserved as-is |

### 11.2 Which project maps to which service (per §36)

| Existing Project | Service (per §36) | Mapping |
|---|---|---|
| `error-explainer` | **ErrorService** | `services/errors/` wraps `internal/{analyze,ollama,vector,history,prompt,render,input,source,repo}/` |
| `webwatch` (web-change-monitor) | **MonitoringService** | `services/monitoring/` wraps the Go binary as a subprocess + reads SQLite via SQLAlchemy; reuses `llm/summarize.py`'s prompt |
| `code-explain` (codebase-explainer-agent) | **DeveloperService** | `services/developer/` calls the Python API in-process (same venv) or via subprocess |
| `grace2.0` (Personal Data Warehouse) | **AnalyticsService** | `services/analytics/` reads `analytics.mart_*` via SQLAlchemy/psycopg; calls `pdw.pipeline.runner.*` to drive syncs |
| RAG / knowledge (notes/documents) | **KnowledgeService** | New — Phase 2 builds pgvector-backed RAG over personal notes & documents |
| LLM layer | **AgentService** | New — `LLMProvider` abstraction per `spec2.md` §15 |

### 11.3 LLM stack reuse — the single biggest win

The three LLM-touching projects each have an Ollama integration today, but **code-explain's is by far the most complete**:

- `code_explain.llm.LLMClient` at `src/code_explain/llm.py:23` already implements **both streaming and tool-calling** (`chat_stream`, `chat_turn`), supports a tool-calls-or-prose-content fallback for models like `qwen2.5-coder`, and caches a `supports_tools` probe via `ollama.show()` (`src/code_explain/llm.py:117`).
- `code_explain.embedder.Embedder` at `src/code_explain/embedder.py:28` already handles `num_ctx`-safe embedding requests (the silent 2048-token truncation footgun for `nomic-embed-text` is mitigated via `CODE_EXPLAIN_EMBED_NCTX`, default 8192).
- `code_explain.prompts.SYSTEM_PROMPT*` at `src/code_explain/prompts.py:5,33,43` are the canonical prompts that should be reused **verbatim** across the OS.

The agent should **not** build a new LLM client. It should either (a) import `code_explain.llm.LLMClient` in-process, or (b) lift it into a top-level `agent/llm.py` module that the four services share. The same goes for `Embedder`.

The error-explainer's `internal/ollama/client.go:54` and webwatch's `llm/summarize.py:51` are **narrow, single-purpose** integrations (error analysis; change summarization with importance rating). They do not need to be replaced — both can keep using their own Ollama clients, with the option to delegate to the shared `LLMProvider` later.

### 11.4 Storage unification (per §9)

| Memory type | Where it lives in the OS |
|---|---|
| Structured (activity, projects, calendar, repos, dates, metrics) | `warehouse.*` schema — the PDW marts (`analytics.*`) plus a few `assistant.*` denormalizations |
| Semantic (notes, documents, code chunks, prior errors) | `knowledge.*` schema backed by **pgvector** (replaces Qdrant and sqlite-vec/LanceDB) |
| Conversation (recent chat, decisions, questions, responses, tool results) | `assistant.{sessions, messages, tool_calls, memories}` per `spec2.md` §8 |

### 11.5 Tool registry shape (per §11)

Initial read-only tools (Phase 3):

| Tool | Service | Backing |
|---|---|---|
| `search_knowledge(query, limit)` | KnowledgeService | pgvector over `knowledge.*` |
| `search_code(repository, query, limit)` | DeveloperService | `code_explain.retriever.Retriever.retrieve` |
| `explain_error(error, repository)` | ErrorService | `error-explainer analyze.Analyze` + (optional) `source.Extract` + Ollama |
| `search_errors(signature)` | ErrorService | pgvector over `knowledge.*` source=`errors` (migrated from Qdrant) |
| `get_activity(start_date, end_date, project)` | AnalyticsService | SQL on `analytics.mart_daily_activity` / `mart_monthly_summary` |
| `get_project_activity(repository)` | AnalyticsService | SQL on `analytics.mart_project_activity` + `fct_commits` |
| `get_calendar(start_date, end_date)` | AnalyticsService | SQL on `analytics.fct_calendar_events` |
| `get_recent_website_changes(limit)` | MonitoringService | Read `webwatch.changes` SQLite + join to summaries |
| `get_website_change(id)` | MonitoringService | Read `webwatch.changes` + `snapshots` |
| `get_repository(name)` | AnalyticsService | SQL on `analytics.dim_repository` |

Each tool declares: name, description, JSON schema, input validation, authorization level (`READ` for all of the above), implementation, structured output (per `spec2.md` §12).

---

## 12. Proposed migration order

Per `spec2.md` §41 (Phases 0-9), and acknowledging that `grace2.0` is already in Phase 2 territory. **The recommendation is to start with the warehouse path because it is the most mature and gives the user value earliest.**

### 12.1 Phase-by-phase plan

| Phase | Scope | Outcome |
|---|---|---|
| **0 — Audit** (now) | This document | Approved by user before any code changes |
| **1 — Unification** | Create parent repo `personal-developer-os/`; vendor or path-reference the four projects; introduce `services/{knowledge,developer,errors,monitoring,analytics}/` interfaces; `.env.example` + Makefile | Each project reachable via a stable interface; **zero existing functionality broken** |
| **2 — Storage and Memory** | Single Postgres container with **pgvector**; `warehouse`, `assistant`, `knowledge` schemas; assistant.{sessions,messages,tool_calls,memories}; migrate error-explainer's Qdrant history to `knowledge.errors` (pgvector); standardize embedding via `code_explain.embedder.Embedder`; rebuild `code-explain`'s store against pgvector (keep per-repo index OR cross-repo index — decide in Phase 1) | One vector store; one embedding client; one structured-memory substrate |
| **3 — Tool Layer** | Implement the 10 read-only tools in §11.5 with JSON schemas, authorization levels, structured outputs | Tools callable directly (no LLM yet) for eval coverage |
| **4 — LLM Agent** | `LLMProvider` abstraction (§15); system prompt (§16); context construction (§17); agent loop with limits (§13-14) | `pdo ask "What did I work on this week?"` works end-to-end |
| **5 — CLI** | `pdo` Typer CLI per §40; Rich streaming output; `/help /tools /memory /clear /session /quit` | MVP — Milestone 1-2 complete |
| **6 — Web API/UI** | FastAPI per §33; minimal chat UI per §34 | Milestone 3-5 (multi-tool flows) |
| **7 — Actions** | Write tools with confirmation per §22-23 | Milestone 7 |
| **8 — Proactive** | Scheduler + notifications per §25 | Milestone 8 |
| **9 — Hardening** | Eval suite (§32), security tests, observability (§30), CI/CD | "Done" |

### 12.2 Closest-to-ready projects

| Project | Closest to | What still blocks |
|---|---|---|
| **grace2.0** | **Phase 2 territory** (storage/memory done for warehouse side) | Needs (a) pgvector addition, (b) `assistant.*` schema, (c) `AnalyticsService` interface, (d) read-only tools |
| **code-explain** | **Phase 3 territory** (tool layer half-built — `code-explain agent` is a working Stage-3 loop) | Needs (a) vector store swap to pgvector, (b) wrapping in `DeveloperService`, (c) standardized `LLMProvider` |
| **error-explainer** | **Phase 3 territory** (single-shot tool, history feature present) | Needs (a) Qdrant→pgvector migration, (b) `ErrorService` interface, (c) structured-output tool result schema |
| **webwatch** | **Phase 3 territory for `MonitoringService`** (read API is just SQL on SQLite + the polyglot summarize call) | Needs (a) zero tests written, (b) `MonitoringService` interface, (c) Chrome/Chromium in container, (d) preserved polyglot seam |

### 12.3 Recommended first integration milestone

**Phase 1 + Phase 2 lite combined:**

1. Stand up `personal-developer-os/` with the layout in the Top-of-Doc Summary.
2. Bring in `grace2.0/` unchanged under `data/ingestion/` and `data/dbt/`.
3. Add pgvector to the existing `docker-compose.yml` Postgres service.
4. Add `assistant.*` and `knowledge.*` schemas (assistant.{sessions, messages, tool_calls, memories}; knowledge.{notes, errors, code_chunks} with `embedding vector(<dim>)`).
5. Build `services/analytics/` against the existing dbt marts.
6. Build `agent/tools/get_activity.py` + `get_project_activity.py` with full test coverage using a mocked DB.
7. Build the `LLMProvider` + `agent/agent.py` + system prompt.
8. Wire up `pdo ask "What did I work on this week?"` end-to-end against a real LLM (Anthropic or local Ollama).
9. Run the `evals/questions.json` cases from `spec2.md` §32 against this flow.

This delivers **Milestones 1 + 2** from `spec2.md` §42 in the smallest possible footprint, with no write actions, no web UI, no monitoring integration, no code search — just the one flow that the user has the most reason to care about. Once this works end-to-end, the same template (service interface → tool → tool test → eval case) scales out to `ErrorService`, `DeveloperService`, `MonitoringService`, and `KnowledgeService`.

---

## Appendix — Cross-cutting inventory

### A.1 Shared environment variables

| Variable | Read by | Purpose |
|---|---|---|
| `DATABASE_URL` | grace2.0 (host-run) | Postgres DSN for ingestion |
| `DBT_POSTGRES_HOST/USER/PASSWORD/PORT/DB/SCHEMA` | dbt container (grace2.0) | Container-side overrides |
| `POSTGRES_USER/PASSWORD/DB/PORT` | docker-compose (grace2.0) | Local PG bootstrap |
| `DBT_SCHEMA` | dbt | Target schema (default `analytics`) |
| `OLLAMA_HOST` | error-explainer (`internal/ollama/client.go:54`), code-explain (`Config._env_config`), webwatch (`llm/summarize.py:51`) | Ollama base URL (default `http://localhost:11434`) |
| `OLLAMA_MODEL` | error-explainer | Default chat model (e.g. `qwen2.5:7b`) |
| `CODE_EXPLAIN_LLM_MODEL` | code-explain | Default chat model (e.g. `qwen2.5-coder:7b`) |
| `CODE_EXPLAIN_EMBED_MODEL` | code-explain | Embedding model (default `nomic-embed-text`) |
| `CODE_EXPLAIN_EMBED_DIM` | code-explain | Embedding vector dim (default 768) |
| `CODE_EXPLAIN_OLLAMA_HOST` | code-explain | Ollama base URL |
| `CODE_EXPLAIN_VECTOR_BACKEND` | code-explain | `sqlite` (default) or `lancedb` |
| `EXPLAIN_REPO` | error-explainer | Default git repo for source extraction |
| `EXPLAIN_CONTEXT_LINES` | error-explainer | Default half-window of source lines |
| `EXPLAIN_VECTOR_HOST` | error-explainer | Qdrant base URL (default `http://localhost:6333`) |
| `EXPLAIN_EMBED_MODEL` | error-explainer | Embed model for history |
| `EXPLAIN_HISTORY` | error-explainer | Disable history (`0`/`false`/`no`) |
| `EXPLAIN_HISTORY_THRESHOLD` | error-explainer | Cosine threshold (default 0.85) |
| `EXPLAIN_COLLECTION` | error-explainer | Qdrant collection (default `explain-errors`) |
| `GITHUB_TOKEN` | grace2.0 | GitHub PAT for `pdw sync github*` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | grace2.0 | OAuth client for Calendar + Gmail |
| `GOOGLE_REFRESH_TOKEN` | grace2.0 | Written by `pdw auth google` |
| `GOOGLE_CALENDAR_ID` | grace2.0 | Calendar to sync (default `primary`) |
| `SPOTIFY_CLIENT_ID` | grace2.0 | Spotify app client id (PKCE, no secret) |
| `SPOTIFY_REFRESH_TOKEN` | grace2.0 | Written by `pdw auth spotify` |
| `LLM_API_KEY` | grace2.0 (reserved) | For the deferred AI/query layer (Milestone 4) |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | new (per `spec2.md` §15, §39) | OS-level provider abstraction |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` | new (per `spec2.md` §39) | OS-level embedding config |
| `MAX_AGENT_STEPS` / `MAX_TOOL_CALLS` / `TOOL_TIMEOUT_SECONDS` | new (per `spec2.md` §14, §39) | Agent safety limits |

### A.2 Shared runtime

| Runtime | Used by | Notes |
|---|---|---|
| **Python 3.10+** (grace2.0 requires 3.12; code-explain pins 3.10+) | code-explain, grace2.0, the new `pdo` CLI, FastAPI assistant-api | Phase 1 should standardize on **3.12** as the lowest common version |
| **Go 1.21+** (error-explainer; webwatch uses 1.26) | error-explainer, webwatch | The two Go services are invoked as subprocesses; toolchain versions can drift |
| **PostgreSQL 16** (via colima/Docker) | grace2.0, new assistant + knowledge schemas | `postgres:16-alpine` + pgvector; add to `docker-compose.yml` |
| **dbt container** (`ghcr.io/dbt-labs/dbt-postgres:1.9.0`) | grace2.0 | Runs on demand via `make dbt` |
| **Ollama** (local) | error-explainer, webwatch, code-explain | All three call `http://localhost:11434`; the OS should not require Ollama (the `LLMProvider` abstraction lets it use Anthropic instead) |
| **Qdrant** (local) | error-explainer (transitional) | Phase 2 retires this in favor of pgvector |
| **Chrome/Chromium** (system or `chrome_path`) | webwatch (`chromedp v0.16.0`) | Phase 1 must decide: Docker image with Chromium, or document the system dep |
| **Docker Compose v2** | grace2.0, new assistant-api/web | `docker-compose.yml` already in grace2.0; the parent repo extends it |

### A.3 Shared SDKs

| SDK | Used by |
|---|---|
| **`httpx>=0.27`** | grace2.0 (`pdw/connectors/base.py:51`); the OS Python services |
| **`pydantic>=2.6` + `pydantic-settings>=2.2`** | grace2.0; the OS Python services |
| **`click>=8.1`** | grace2.0 (`pdw` CLI) |
| **`typer>=0.12`** | code-explain; the new `pdo` CLI |
| **`rich>=13.7`** | code-explain; the new `pdo` CLI |
| **`ollama>=0.3`** | code-explain (the only project that uses a real SDK) |
| **`cobra`** | error-explainer v1.10.2, webwatch v1.8.1 (different versions, independent — invoked as subprocesses) |
| **`chromedp v0.16.0`** | webwatch |
| **`modernc.org/sqlite v1.29.6`** | webwatch (pure-Go, no CGO) |
| **`tree-sitter>=0.23` + `tree-sitter-language-pack>=1.14`** | code-explain |
| **`sqlite-vec>=0.1.9`** (transitional) | code-explain |
| **`lancedb>=0.10`** (optional, transitional) | code-explain |
| **`psycopg[binary]>=3.1.18`** | grace2.0; the OS Python services |
| **`pathspec>=0.12`** | code-explain |
| **`pytest>=8.0`** | grace2.0 (22 files), code-explain (12 files), error-explainer (6 files via stdlib `go testing`) |
| **`ruff>=0.4`** | grace2.0 (lint) |

### A.4 The LLM stack already present in code-explain — what it is and how to reuse it

**Provider:** local Ollama via the `ollama` Python SDK (`src/code_explain/llm.py:26`, `src/code_explain/embedder.py:34`).

**Model:** `qwen2.5-coder:7b` for chat; `nomic-embed-text` for embeddings (both configurable via `CODE_EXPLAIN_LLM_MODEL` / `CODE_EXPLAIN_EMBED_MODEL`).

**Prompting pattern:**

- A canonical `SYSTEM_PROMPT` (`src/code_explain/prompts.py:5`) instructs the model to use the provided context, cite by path:line, and not invent.
- `SYSTEM_PROMPT_GRAPH` (`src/code_explain/prompts.py:33`) is the variant that uses the caller/callee graph.
- `SYSTEM_PROMPT_AGENT` (`src/code_explain/prompts.py:43`) drives the Stage-3 tool-calling agent.
- `CONTEXT_HEADER_TEMPLATE` (`src/code_explain/prompts.py:25`) is the per-chunk citation header — `FILE/<path>/L<start>-<end> (<kind>: <symbol>)` — that makes every RAG answer traceable.
- For tool calling, the agent `code_explain/agent.py:72 TOOLS_SPEC` defines a tool schema and `build_handlers` at `agent.py:316` dispatches them; the model can return tool calls either as a structured `tool_calls` field **or** as JSON embedded in the content (the agent handles both for `qwen2.5-coder`).

**Reuse opportunity.** This stack is **the foundation the OS agent should build on, not replace.** Specifically:

1. **Promote `code_explain.llm.LLMClient` to `agent/llm.py`** and rename it as the OS's `LLMProvider` impl for Ollama. Add an Anthropic impl behind the same interface per `spec2.md` §15. Both impls expose `generate(messages, tools=None) -> LLMResponse`; `chat_stream` becomes a thin wrapper that yields deltas.
2. **Promote `code_explain.embedder.Embedder` to `agent/embedder.py`** and have every service that needs embeddings (knowledge, errors, code) instantiate one. Standardize the embedding dim in `LLMConfig.embed_dim` (default 768 from `nomic-embed-text`).
3. **Reuse the prompts verbatim.** `SYSTEM_PROMPT`, `CONTEXT_HEADER_TEMPLATE`, and the tool schema from `TOOLS_SPEC` are working artifacts — copy them into `agent/prompts/` and adapt only when a new tool needs a new prompt.
4. **Reuse the streaming + tool-calling dispatch.** `chat_stream`'s handling of "tool calls in content vs in structured field" is exactly the agent-loop pattern from `spec2.md` §13.

The two narrow LLM integrations (error-explainer's stdlib `internal/ollama/client.go:54`, webwatch's `llm/summarize.py:51`) are **specialized prompts** (error analysis; change summarization with importance rating). They should keep their own Ollama clients and be migrated to the shared `LLMProvider` only when there's a concrete reason (e.g., switching the user from Ollama to Anthropic).

---

## Stop point

This document is the Phase 0 deliverable. Per `spec2.md` §50 ("Then stop and present the plan before making major architectural changes"), **no code has been written and no files outside `docs/integration-audit.md` have been modified.** Before Phase 1 begins, the user should review and decide:

1. **Parent-repo layout (§Top + §11):** confirm `services/<name>/` per project, or restructure.
2. **First integration milestone (§12.3):** the Phase 1 + Phase 2 lite combo targeting `grace2.0`'s warehouse path. Approve, or reorder (e.g., start with code-explain's RAG path instead).
3. **Vector store strategy (§11.4):** standardize on pgvector in Phase 2, retire Qdrant and sqlite-vec/LanceDB. Confirm the cross-repo vs per-repo `code-explain` index decision.
4. **LLM provider strategy (§11.3 + Appendix A.4):** promote `code_explain.llm.LLMClient` to `agent/llm.py` as the shared Ollama impl, add Anthropic as a second provider. Confirm Ollama-only-for-MVP vs Anthropic-from-day-one.
5. **Top three risks (Top-of-Doc Summary):** the two-vector-store incompatibility, the LLM-provider lock-in across three projects, and the lack of tests in webwatch + error-explainer `cmd/`/`main.go`. Confirm the mitigation order.

Once these five decisions are made, Phase 1 can begin: stand up `personal-developer-os/`, vendor the four projects, introduce the five service interfaces, write `.env.example`, add a smoke test per existing project, and produce a working `pdo` that wraps each project's CLI. No write actions; no LLM agent; just stable service interfaces and the first two `AnalyticsService` tools (`get_activity`, `get_project_activity`).
