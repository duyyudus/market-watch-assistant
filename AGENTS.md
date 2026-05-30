# Repository Guidelines

## Project Layout

- This repository is intended to become `market-watch-assistant`, a personal market watch system with two main top-level directories: `market-watch-bot/` and `dashboard/`.
- `market-watch-bot/` houses the unified Python backend services, containing three equal packages:
  - `bot_worker/`: Standalone background worker responsible for market/news ingestion, event clustering, scoring, alert decisions, digests, retention, embeddings, and maintenance jobs.
  - `api_server/`: FastAPI control/data access layer between the dashboard and shared database. It should not run bot jobs directly.
  - `common/`: Shared core package containing database models (`common.db.models`), session helpers (`common.db.session`), configuration settings (`common.config`), and logging (`common.logging`).
- `dashboard/` is the React/Vite/Tailwind/daisyUI user-facing control panel.
- `docker-compose.yml` is planned for shared infrastructure and service orchestration.
- `brief/` contains the high-level product, architecture, and CLI reference docs. Read these before making architectural changes or adding new components.
- `market-watch-bot/alembic/` contains the current database migrations.
- `market-watch-bot/tests/` contains the pytest suite (including both bot worker and API contract tests).

## System Architecture

The assistant collects global, Vietnam, and crypto market signals, organizes them into market events, alerts only when useful, and exposes configuration and monitoring through a web dashboard.

The unified backend component responsibilities are:

- `bot_worker`: standalone background service and CLI for source management, scheduled ingestion, normalization, deduplication, event clustering, market data joins, scoring, alert generation, digest generation, embeddings/vector indexing, and retention.
- `api_server`: FastAPI service for source/watchlist/asset/alert/digest/event browsing, bot status, health, and manual command APIs. It communicates with the bot through shared Postgres tables, not in-process imports or dynamic function calls.
- `common`: Shared database mappings, configurations, and core logging setup.
- Shared infrastructure: Postgres with pgvector, Alembic migrations, and Docker Compose.

The core bot design is deterministic first: detect possible market events, cluster related reports, verify/classify/score them, decide whether to alert, and preserve compact event history. Use agentic/LLM modules selectively for high-value uncertain events, unexplained price moves, and deeper explanations.

## Tooling And Commands

Use `uv` for Python dependency and command execution. The implemented commands below apply to `market-watch-bot/`.

```bash
cd market-watch-bot
uv run pytest
uv run pytest tests/test_cli.py
uv run ruff check .
uv run market-watch --help
uv run market-watch pipeline run --dry-run
uv run market-watch server start
```

Database-backed commands read `DATABASE_URL` from `.env` or the process environment. The default URL points to a shared Postgres host defined in `common/config.py`, so avoid running migrations, destructive source operations, or live pipeline commands unless that is explicitly intended.

Common live/setup commands:

```bash
cd market-watch-bot
uv run market-watch init
uv run market-watch doctor
uv run market-watch migrate
uv run market-watch source list
```

Future component expectations from the brief:

- `dashboard/`: TypeScript, React, Vite, Tailwind CSS, daisyUI, `.env`.
- Shared infrastructure should be managed with Docker Compose where practical.

## Coding Conventions

- Target Python 3.12.
- Keep line length at 100 characters.
- Ruff is configured with `E`, `F`, `I`, `UP`, `B`, and `SIM`; fix lint violations before handing off.
- Prefer typed, small functions and existing service helpers in `bot_worker/services.py` over duplicating database workflow code in CLI handlers.
- Use async SQLAlchemy patterns already present in `common/db/session.py` and CLI `_with_session` helpers.
- Keep comments sparse and only where they clarify non-obvious behavior.
- **For new API work, keep bot execution decoupled.** Even though the API server and worker share the same repository and Python virtual environment, the API MUST write command/status records in Postgres (the `bot_commands` queue table) and must NEVER call worker pipelines directly in-process during HTTP cycles.
- For new dashboard work, route backend state changes through the API server rather than directly coupling to bot implementation details.

## Testing Guidance

- Add or update focused tests in `market-watch-bot/tests/` for behavior changes.
- Test both background workers and API endpoints locally inside `market-watch-bot/tests/`.
- Prefer dry-run or unit-level tests for pipeline and CLI work when possible.
- Tests should not require network access or a live database unless clearly marked and requested.
- For CLI changes, use existing Typer test patterns in `tests/test_cli.py`.
- For migration/model changes, verify both tests and Alembic upgrade behavior where feasible.

## Configuration And Runtime Files

- Each component should have its own `.env`; Python components should also have their own `settings.yml`.
- `market-watch-bot/settings.yml` holds the bot's and API's non-secret defaults (including `api_cors_origins`).
- `market-watch-bot/.env` is generated by `market-watch init` and should remain untracked.
- Relevant environment variables include `DATABASE_URL`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `API_BASE_URL`, `REDIS_URL`, and `API_CORS_ORIGINS`.
- Runtime logs default to `.log/market-watch-bot.log`; do not commit logs or generated runtime files.
- The bot and API server share the same Postgres database URL loaded through the unified configuration layer.

## CLI Scope

The implemented CLI entry point is `market-watch = bot_worker.cli:app`.

Current command groups include `source`, `worker`, `job`, `pipeline`, `news`, `event`, `watchlist`, `alert`, `digest`, `retention`, `health`, `embedding`, `market`, `catalyst`, and `server`. Check `bot_worker/cli.py` and `uv run market-watch --help` before assuming a command from `brief/` is implemented.

Use explicit confirmations for destructive flows. `source purge` already requires `--confirm`; preserve that pattern for any new destructive command.

The CLI manual in `brief/market-watch-bot-cli-manual.md` is a target/reference command set and may include commands that are not implemented yet.

## Agent Workflow Notes

- Inspect both `brief/` and existing implementation before editing.
- Keep changes scoped to the requested behavior and avoid unrelated refactors.
- Do not revert user changes in the working tree.
- If a task touches live market data, OpenRouter embeddings, Telegram alerts, or the shared database, state that dependency and prefer a dry-run or mocked test path first.
