# Market Watch Assistant 1.0 Roadmap Progress

Updated: 2026-05-31

## Track 1: Infrastructure & Deployment

Status: Completed

### 1.1 Docker Compose Stack

- Added a top-level multi-stage `Dockerfile` with targets for `bot-worker`, `api-server`, and `dashboard`.
- Added `docker-compose.yml` for the three app services only. The stack expects `market-watch-bot/.env` to provide `DATABASE_URL`; it does not start Postgres.
- Added healthchecks for all services.
- Mounted `market-watch-bot/.env`, `settings.yml`, and `.log/` into backend containers.
- Added dashboard-to-API `depends_on` with `service_healthy`.

### 1.2 API Authentication Layer

- Added `API_AUTH_TOKEN` to settings and `market-watch-bot/.env.example`.
- Added FastAPI middleware requiring `Authorization: Bearer <token>` for `POST`, `PATCH`, `PUT`, and `DELETE`.
- Kept read-only endpoints open for monitoring.
- Added dashboard bearer-token support via optional `VITE_API_AUTH_TOKEN`.

### 1.3 Database Connection Pooling Fix

- Cached async engines and session factories by database URL in the shared DB session helper.
- Updated the worker loop to create settings and the session factory once at startup, then reuse them for each tick.
- Added pool metric reporting with `pool_size`, `checked_out`, and `overflow`.

### 1.4 Database Index Migration

- Added Alembic revision `0008_performance_indexes.py`.
- Added indexes for command polling, normalized news processing status, alert dispatch, investigation queue, event cluster recency, and descending job run status display.

### 1.5 Secure Configuration & Decoupled Secrets

- Removed the hardcoded LAN database fallback from `common/config.py`.
- Enforced `DATABASE_URL` through `.env` or process environment.
- Added Telegram token redaction for alert delivery errors, provider responses, CLI JSON output, CLI DB errors, and bot logger handlers.

### 1.6 Deferred Settings Loading

- Removed API settings and DB engine/session creation from import time.
- Added request-time settings/session dependencies that can be overridden in tests.
- Added DB-backed `GET /ready` readiness reporting with pool metrics.

## Verification

- `cd market-watch-bot && uv run pytest` -> 196 passed.
- `cd market-watch-bot && uv run ruff check .` -> all checks passed.
- `cd dashboard && npm test` -> 24 passed.
- `cd dashboard && npm run build` -> build completed.
- `docker compose config` -> Compose syntax rendered successfully.

## Operational Notes

- `docker-compose.yml` mounts `market-watch-bot/.env` into backend containers instead of using Compose `env_file`, so `docker compose config` does not expand local secrets into rendered service environment output.
- No live containers, live migrations, live market-data calls, or live pipeline commands were run.
