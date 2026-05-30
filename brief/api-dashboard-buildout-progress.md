# API + Dashboard Buildout Progress

## Summary

The API server and dashboard are being built in vertical slices against the existing
`market-watch-bot` database. The current implementation is Phase 1 plus early
Phase 2/3 scaffolding.

## Phase 1: Read-Only Monitoring Base

Status: implementation polish complete;

Implemented:

- `api-server/` FastAPI app with independent configuration, DB session, schemas, and models.
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

Status: scaffolded.

Implemented:

- New shared `bot_commands` model and Alembic migration:
  - `market-watch-bot/alembic/versions/0007_bot_commands.py`
- API endpoints:
  - `POST /bot/commands`
  - `GET /bot/commands`
  - `GET /bot/commands/{id}`
  - `POST /bot/commands/{id}/cancel`
- Dashboard command center and command buttons.
- Worker polling hook for pending bot commands.
- Command lifecycle helpers for claim, complete, and fail.
- API degrades gracefully before `bot_commands` migration exists.

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

Remaining:

- Run migration in the shared DB before using command buttons:

  ```bash
  cd market-watch-bot
  uv run market-watch migrate
  ```

- Live-test each command path against the real worker and database.
- Add command-specific dashboard confirmation states for mutating actions.
- Add clearer UI message when command queue is unavailable because migration has not run.

## Phase 4: Operational Depth

Status: not started, except for a few API stubs.

Planned:

- Retention preview/run page.
- Embeddings status page.
- LLM usage/runs diagnostics.
- Catalyst review page.
- Source fetch log page.
- Event score history/timeline.

## Verification So Far

Backend:

- `market-watch-bot`: `uv run pytest`
- `market-watch-bot`: `uv run ruff check .`
- `api-server`: `uv run pytest`
- `api-server`: `uv run ruff check .`

Frontend:

- `dashboard`: `npm run test`
- `dashboard`: `npm run build`

Phase 2 completion checks on 2026-05-30:

- `api-server`: `uv run pytest`
- `api-server`: `uv run ruff check .`
- `market-watch-bot`: `uv run pytest tests/test_scoring.py tests/test_watchlist.py tests/test_alert_policy_settings.py`
- `market-watch-bot`: `uv run ruff check .`
- `dashboard`: `npm run test`
- `dashboard`: `npm run build`

Additional preset ownership checks on 2026-05-30:

- `market-watch-bot`: `uv run pytest`
- `api-server`: `uv run pytest`
- `dashboard`: `npm run test`
- `dashboard`: `npm run build`

Runtime smoke checks performed:

- API health endpoint reachable.
- API CORS works for localhost and private-network Vite origins.
- Dashboard dev server starts on `5173`.

Runtime checks on 2026-05-29:

- `market-watch-bot`: `uv run market-watch migrate` completed against the configured database and seeded 0 starter sources.
- API server started with `./run-server.sh` on `http://localhost:8000`.
- Dashboard dev server started with `./run-ui.sh` on `http://localhost:5173`.
- `curl -s http://localhost:8000/health` returned `{"status":"ok","service":"market-watch-api","environment":"development"}`.
- `curl -s http://localhost:5173` returned the Vite HTML shell.
- **Rendered Browser QA**: Fully completed and verified via Playwright in a headless Chromium session.
  - **Date**: 2026-05-29
  - **Local Services Used**:
    - PostgreSQL database with `pgvector` extension
    - FastAPI `api-server` (running on port 8000)
    - React/TypeScript/Vite/daisyUI `dashboard` (running on port 5173)
  - **Pages Checked (Desktop & Mobile Viewports)**:
    - **Overview**: Verified. Correctly renders responsive layout, metric panels, priority events list, recent alerts, recent jobs, command queue, and manual controls.
    - **Events**: Verified. Renders a correct and friendly empty state ("No priority events yet" / "No event clusters match the current data set") when database is freshly seeded.
    - **News**: Verified. Renders a correct empty state ("No normalized news yet") when database is freshly seeded.
    - **Alerts**: Verified. Renders a correct empty state ("No alert decisions yet") when database is freshly seeded.
    - **Sources**: Verified. Renders configured sources list and supports toggling enabled/disabled state correctly.
    - **Watchlist**: Verified. Strictly read-only visual rendering confirmed (0 input or mutating elements found). Correctly displays `0 assets watched` empty state.
    - **Commands**: Verified. Displays action buttons and queued commands list accurately.
    - **Operations**: Verified. Accurately shows jobs history, alerts history, and source action triggers.
  - **UI/Layout Checks**:
    - Verified no blank panels or broken layouts.
    - Checked desktop width (1280x800) and narrow mobile width (375x667) — verified fluid response, clean panels, no overlapping text, and beautiful mobile-responsive select navigation.
    - Confirmed refresh button functions correctly and pulls fresh data.
  - **Known Limitations**:
    - Watchlist and sources creation/editing forms remain CLI-driven in Phase 1 and are planned for Phase 2.
    - Manual commands in the dashboard are queued in the database but require the bot worker background service to run to process them.


## Current Assumptions

- Personal/local deployment, no authentication in v1.
- API and bot share Postgres.
- API must not import `bot_worker` internals.
- Dashboard must go through API only.
- Bot-triggering actions must flow through `bot_commands`.
- Existing bot Alembic history remains the shared migration source for now.
