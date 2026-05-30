# API + Dashboard Buildout Progress

## Summary

The API server and dashboard are being built in vertical slices against the existing
`market-watch-bot` database. The current implementation is Phase 1 plus early
Phase 2/3 scaffolding.

## Phase 1: Read-Only Monitoring Base

Status: implementation polish complete;

Implemented:

- Integrated `api_server/` FastAPI app inside the `market-watch-bot/` package, sharing models, configurations, sessions, and logging via a unified `common` module.
- Health and monitoring endpoints:
  - `GET /health`
  - `GET /bot/status`
  - `GET /jobs/runs`
  - `GET /sources`
  - `GET /events`
  - `GET /events/{id}`
  - `GET /news`
  - `GET /news/{id}`
  - `GET /alerts`
  - `GET /alerts/{id}`
  - `GET /digests/preview`
  - `GET /market/moves`
  - `GET /investigations`
  - `GET /watchlist`
- `dashboard/` React/Vite/Tailwind/daisyUI app with dark operational theme.
- Dashboard views:
  - Overview
  - Events
  - News
  - Alerts
  - Sources
  - Watchlist
  - Commands
  - Operations
- Dashboard empty/error states:
  - per-resource API errors no longer blank the entire console
  - Overview, Events, News, Alerts, Sources, Watchlist, Commands, and Operations show explicit empty/error states
  - `/watchlist` is Phase 1 read-only monitoring only; watchlist mutation remains Phase 2 configuration
- Root scripts:
  - `run-server.sh`
  - `run-ui.sh`


## Phase 2: Safe Configuration UI

Status: implementation complete.

Implemented:

- Source API:
  - `POST /sources`
  - `PATCH /sources/{id}`
  - `POST /sources/{id}/enable`
  - `POST /sources/{id}/disable`
- Watchlist API:
  - `POST /watchlist`
  - `PATCH /watchlist/{id}`
  - `DELETE /watchlist/{id}`
- Alert policy API:
  - `GET /settings/alert-policy`
  - `PATCH /settings/alert-policy`
- Bot alert decisions can read `app_settings.alert_policy` overrides.
- Dashboard supports source enable/disable.
- Dashboard supports source create/edit forms.
- Dashboard supports watchlist create/edit/delete UI with explicit delete confirmation.
- Dashboard supports alert policy settings.
- Watchlist tier `S` is supported as the highest scoring tier, and API watchlist tier input is normalized to uppercase.
- Source/watchlist form presets are owned by bot settings, seeded into shared `app_settings.configuration_presets` by `market-watch migrate`, exposed by `GET /settings/presets`, and consumed by the dashboard.

## Phase 3: Command Queue And Manual Controls

Status: complete.

Implemented:

- New shared `bot_commands` model and Alembic migration:
  - `market-watch-bot/alembic/versions/0007_bot_commands.py`
- API endpoints with strict command-specific payload validation and graceful degradation:
  - `POST /bot/commands` (validates schemas per command type, returning `422` on errors, and returns `503` if `bot_commands` table is missing)
  - `GET /bot/commands`
  - `GET /bot/commands/{id}`
  - `POST /bot/commands/{id}/cancel`
- Dashboard manual control center with complete selectors and buttons:
  - Supports dry-run and live pipeline run, alert dispatch preview/live send, event rescore/investigate/mark dropdown forms, recluster preview/apply, source fetch, and retention preview/run.
  - Safe confirmation modal/dialog (`ConfirmDialog.tsx`) using daisyUI styles for all destructive/mutating actions.
  - Displays queue-unavailable state gracefully on Overview and Commands pages with explicit migration instructions when database has not been migrated.
  - Command table displays detailed timestamps (`started_at`, `completed_at`), dynamic status badges, expandable JSON results, and error message blocks.
- Robust worker polling with row-level locking (`with_for_update(skip_locked=True)`) to ensure single-claiming in concurrent scenarios.
- Command lifecycle helpers for claim, complete, and fail.
- Automated API, worker, and dashboard test suites verifying correct operation, validation, database robustness, and dialog flows.

Allowed command types:

- `pipeline.run`
- `source.fetch`
- `alert.dispatch`
- `event.rescore`
- `event.mark`
- `event.recluster`
- `investigation.run_event`
- `retention.preview`
- `retention.run`

## Phase 4: Operational Depth

Status: not started, except for a few API stubs.

Planned:

- Retention preview/run page.
- Embeddings status page.
- LLM usage/runs diagnostics.
- Catalyst review page.
- Source fetch log page.
- Event score history/timeline.


## Current Assumptions

- Personal/local deployment, no authentication in v1.
- API and bot share Postgres.
- API must remain decoupled from bot execution (no in-process bot jobs during HTTP cycles). It can import shared constants, DB models, schemas, and configurations from `bot_worker` or `common`, but all runtime bot triggering must be asynchronous via the `bot_commands` database queue.
- Dashboard must go through API only.
- Bot-triggering actions must flow through `bot_commands`.
- Existing bot Alembic history remains the shared migration source for now.
