# Repository Guidelines

## Project Layout

- This repository is `market-watch-assistant`, a personal market watch system with a
  Python backend, React dashboard, Docker targets, and product/architecture briefs.
- `market-watch-bot/` houses the unified Python backend under one `uv` environment:
  - `bot_worker/`: background worker, Typer CLI, ingestion pipeline, clustering,
    scoring, alert/digest delivery, LLM/embedding helpers, investigations, retention,
    market data joins, and service-layer workflow code.
  - `api_server/`: FastAPI control and data access layer for the dashboard. It exposes
    route groups for health, bot commands, jobs, sources, events, news, alerts, digests,
    market data, investigations, watchlists, settings, and maintenance.
  - `common/`: shared database models/session helpers, configuration, logging, source
    parsing/policies, normalization, crawler/article utilities, LLM client helpers, and
    bot command records.
- `market-watch-bot/bot_worker/cli/` contains the Typer CLI modules registered by
  `bot_worker.cli:app`.
- `market-watch-bot/bot_worker/services/` contains the shared worker/service operations
  used by CLI commands and background workflows. Prefer extending these modules over
  duplicating database or pipeline logic in CLI handlers.
- `market-watch-bot/api_server/app/` contains FastAPI routers, schemas, services, and
  database dependencies.
- `market-watch-bot/alembic/` contains the current database migrations.
- `market-watch-bot/tests/` contains the backend pytest suite, including worker,
  service, migration, CLI, and API contract tests.
- `dashboard/` is the React 19, Vite, TypeScript, Tailwind CSS, daisyUI dashboard.
  Source code is organized under `dashboard/src/app`, `components`, `features`, `hooks`,
  `lib`, and `types`; Playwright tests live in `dashboard/e2e/`.
- `Dockerfile` and `docker-compose.yml` are implemented for `bot-worker`, `api-server`,
  and `dashboard` service targets.
- `brief/` contains product, architecture, roadmap, implementation recap, and CLI
  reference docs. Read the relevant brief before architectural changes or new major
  components.

## System Architecture

The assistant collects global, Vietnam, and crypto market signals, organizes them into
market events, alerts only when useful, and exposes configuration and monitoring through
the dashboard.

The unified backend responsibilities are:

- `bot_worker`: standalone background service and CLI for source management, scheduled
  ingestion, normalization, deduplication, full-text extraction, event clustering,
  market data joins, scoring, alert generation/delivery, digest generation, embeddings,
  LLM analysis, investigations, retention, and operational maintenance.
- `api_server`: FastAPI service for source/watchlist/news/event/alert/digest/market/
  investigation/settings/maintenance browsing and mutation APIs. It communicates with
  the worker through shared database tables and `bot_commands`, not in-process pipeline
  calls during HTTP cycles.
- `common`: shared SQLAlchemy mappings, async session helpers, configuration loading,
  logging setup, source parsing/policy utilities, normalization, crawler/article
  helpers, and external API client primitives.
- Shared infrastructure: Postgres with pgvector, Alembic migrations, Docker Compose,
  and runtime configuration from `.env` plus `settings.yml`.

The core bot design is deterministic first: detect possible market events, cluster
related reports, verify/classify/score them, decide whether to alert, and preserve compact
event history. Use LLM, embedding, and investigation modules selectively for high-value
uncertain events, ambiguous clusters, unexplained price moves, and deeper explanations.

## Tooling And Commands

Use `uv` for Python dependency and command execution. Backend commands apply inside
`market-watch-bot/`.

```bash
cd market-watch-bot
uv run pytest
uv run pytest tests/test_cli.py
uv run pytest tests/test_api_contract.py
uv run ruff check .
uv run market-watch --help
uv run market-watch pipeline run --dry-run
uv run market-watch worker start
uv run market-watch server start
```

Database-backed commands read `DATABASE_URL` from `.env` or the process environment.
Avoid migrations, destructive source operations, live pipeline runs, live embeddings,
LLM calls, investigations, Telegram delivery, or market-data fetches unless that is
explicitly intended.

Common backend setup/live commands:

```bash
cd market-watch-bot
uv run market-watch init
uv run market-watch doctor
uv run market-watch migrate
uv run market-watch source list
uv run market-watch worker health
```

Dashboard commands apply inside `dashboard/`.

```bash
cd dashboard
npm install
npm run dev
npm run build
npm run test
npm run lint
npm run e2e
```

The unified Docker build script can run the implemented service targets from the repository root:

```bash
./docker-build local --env-file .env.local
```

## Coding Conventions

- Target Python 3.12.
- Keep Python line length at 100 characters.
- Ruff is configured with `E`, `F`, `I`, `UP`, `B`, and `SIM`; fix lint violations
  before handing off Python changes.
- Prefer typed, small functions and existing service helpers in
  `bot_worker/services/` over duplicating database workflow code in CLI handlers or API
  routers.
- Use async SQLAlchemy patterns already present in `common/db/session.py`,
  `api_server/app/db/session.py`, and CLI `_with_session` helpers.
- Keep comments sparse and only where they clarify non-obvious behavior.
- For new API work, keep bot execution decoupled. The API server and worker share the
  repository and database, but HTTP request handlers must not call worker pipelines
  directly. Queue work through `bot_commands` or shared persistent state.
- For new dashboard work, route backend state changes through the API server rather than
  coupling to bot implementation details.
- For React work, follow the existing feature/component layout, reuse shared components
  from `dashboard/src/components`, keep API types in `dashboard/src/api.ts` or
  `dashboard/src/types`, and use lucide icons where icon buttons are appropriate.

## Testing Guidance

- Add or update focused tests for behavior changes.
- Backend tests live in `market-watch-bot/tests/`; use pytest and existing Typer/FastAPI
  test patterns.
- Dashboard unit/component tests use Vitest; end-to-end tests use Playwright.
- Prefer dry-run, in-memory SQLite, mocked HTTP, or unit-level tests for pipeline, CLI,
  API, and dashboard work when possible.
- Tests should not require network access, OpenRouter, Brave Search, Telegram, live
  market-data services, or a live database unless clearly marked and explicitly requested.
- For migration/model changes, verify focused tests and Alembic upgrade behavior where
  feasible.
- For API changes, include or update API contract tests and keep write endpoints covered
  for bearer-token behavior when relevant.

## Configuration And Runtime Files

- Backend configuration is loaded from `market-watch-bot/.env` and
  `market-watch-bot/settings.yml`.
- `market-watch-bot/settings.yml` holds non-secret defaults for bot, ingestion, alerts,
  embeddings, LLM, investigation, market data, presets, retention, and logging.
- `market-watch-bot/.env` is generated by `market-watch init` and should remain
  untracked.
- `DATABASE_URL` is required by `common.config.load_settings()`.
- Relevant backend environment variables include `DATABASE_URL`, `OPENROUTER_API_KEY`,
  `BRAVE_SEARCH_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `API_AUTH_TOKEN`,
  `REDIS_URL`, and `API_CORS_ORIGINS`.
- API mutating requests require `API_AUTH_TOKEN`; the dashboard can provide it with
  `VITE_API_AUTH_TOKEN`.
- Dashboard environment variables include `VITE_API_BASE_URL` and
  `VITE_API_AUTH_TOKEN`. If `VITE_API_BASE_URL` is unset, the dashboard derives
  `http://<current-host>:8000`.
- Runtime logs default to `market-watch-bot/.log/market-watch-bot.log`; do not commit
  logs, `.env`, generated runtime files, or build artifacts.

## CLI Scope

The implemented CLI entry point is `market-watch = bot_worker.cli:app`.

Current top-level commands and groups include `init`, `migrate`, `doctor`, `source`,
`worker`, `job`, `pipeline`, `news`, `event`, `watchlist`, `alert`, `digest`,
`retention`, `health`, `embedding`, `market`, `catalyst`, `llm`, `investigate`, and
`server`. Check `bot_worker/cli/`, `brief/market-watch-bot-cli-current-spec.md`, and
`uv run market-watch --help` before assuming a command exists.

Use explicit confirmations for destructive flows. `source purge` requires `--confirm`;
preserve that pattern for any new destructive command.

The CLI reference in `brief/market-watch-bot-cli-current-spec.md` is the current
recommended command surface. Older MVP brief files may describe target or historical
commands that are not implemented.

## Agent Workflow Notes

- Inspect relevant files under `brief/` and the existing implementation before editing
  architectural boundaries, CLI shape, data models, or dashboard flows.
- Keep changes scoped to the requested behavior and avoid unrelated refactors.
- Do not revert user changes in the working tree.
- If a task touches live market data, OpenRouter embeddings/LLM, Brave Search,
  Telegram alerts, Docker services, or the shared database, state that dependency and
  prefer a dry-run or mocked test path first.
- Before handing off code changes, run the narrowest useful validation command and
  report any tests or checks that were not run.
