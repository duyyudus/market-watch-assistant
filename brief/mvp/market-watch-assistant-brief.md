# Market Watch Assistant — High-Level Implementation Brief

## Objective

Build a personal market watch assistant covering global markets, Vietnam markets, and crypto. The app should collect and process market-related news/signals, organize them into useful alerts and summaries, and expose configuration/monitoring through a web dashboard.

The system is structured as follows:

```txt
market-watch-assistant/
  market-watch-bot/
    bot_worker/
    api_server/
    common/
  dashboard/
  docker-compose.yml
```

Shared infrastructure:

```txt
Postgres + pgvector
Alembic migrations
Docker / Docker Compose
Separate .env per component
Separate app settings .yml per component (for python apps only)
```

---

# 1. Market-watch Bot

## Purpose

The `market-watch worker` is a standalone background service responsible for market monitoring jobs. It should run independently from the API server and dashboard.

It handles:

```txt
source registration/removal
scheduled market/news watch jobs
RSS/API/feed ingestion
event processing
embedding/vector indexing
alert generation
alert delivery
digest generation
maintenance/cleanup jobs
```

Detailed pipeline, clustering, scoring, and agentic investigation logic are documented separately here: [market-watch-bot specs](market-watch-bot-architect-and-data-pipeline.md)

## Technology

Recommended:

```txt
Python
uv for package management
Postgres
pgvector
Typer or Click for CLI
YAML config
.env for secrets/runtime environment
```

## Directory

```txt
market-watch-bot/
  pyproject.toml
  uv.lock
  .env
  settings.yml
  alembic.ini
  alembic/
  bot_worker/
    cli/
    ...
  api_server/
    app/
      main.py
      schemas/
      routers/
      services/
  common/
    config.py
    logging.py
    db/
      models.py
      session.py
```

## CLI Support

The bot should provide a CLI for essential operations. See more details here: [market-watch-bot-cli manual](market-watch-bot-cli-manual.md)


---

# 2. API Server

## Purpose

The API server is the control and data access layer between the dashboard and the database.

It should expose APIs for:

```txt
source management
watchlist management
alert rule management
alert channel management
event/news browsing
digest browsing
bot job/status monitoring
manual trigger commands
```

The API server should not run the market watch jobs itself.

## Technology

```txt
Python
FastAPI
uv for package management
Postgres
SQLAlchemy or SQLModel
Alembic
pgvector
Pydantic
YAML config
.env for secrets/runtime environment
```

## Directory

```txt
market-watch-bot/api_server/
  app/
    main.py
    schemas/
    routers/
    services/
```

## API Responsibilities

The API server should manage:

```txt
Feed sources
Watchlists
Assets/tickers
Alert rules
Alert channels
Bot commands
Bot run status
News/event browsing
Digest browsing
System health
```

## Example API Domains

```txt
/sources
/watchlists
/assets
/events
/alerts
/alert-channels
/digests
/bot/commands
/bot/status
/health
```

## Bot Interaction

The API server should communicate with the bot through shared Postgres tables, not direct in-process calls.

Example command model:

```txt
api-server writes:
  bot_commands

market-watch-bot reads:
  pending bot_commands

market-watch-bot writes back:
  status, result, error, completed_at
```

This keeps the bot decoupled and easier to debug.

---

# 3. Dashboard

## Purpose

The dashboard is the user-facing control panel for the assistant.

It should allow the user to:

```txt
view market events and alerts
manage news/feed sources
manage watchlists
configure alert rules
configure alert channels
view bot status
trigger manual jobs
review digests
inspect event clusters
```

## Technology

```txt
TypeScript
React.js
daisyUI
Tailwind CSS
Vite
.env for runtime environment
```

## Directory

```txt
dashboard/
  package.json
  .env
  src/
    main.tsx
    app/
    components/
    pages/
    api/
    hooks/
    layouts/
    styles/
```

## UI Areas

Recommended dashboard sections:

```txt
Overview
Events
Alerts
Sources
Watchlists
Alert Rules
Alert Channels
Digests
Bot Status
Settings
```

## UI Stack

Use:

```txt
React.js for frontend
TypeScript for type safety
daisyUI for theme/components
Tailwind CSS for layout/styling
```

The dashboard should call the API server only. It should not connect directly to Postgres.

---

# Database

Use one shared Postgres database for both `api_server` and `bot_worker` under the `market-watch-bot` repository.

Database URL is configured in the unified `market-watch-bot/.env` file and read by the shared `common` module. Use this DB: `postgresql+asyncpg://postgres:postgres@192.168.100.39:5432/market_watch_assistant`

Required extensions:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Use `pgvector` for storing embeddings used by news/event similarity search.

## Migration

Use Alembic for database migrations.

Recommended ownership:

```txt
market-watch-bot/alembic owns database migrations
Both api_server and bot_worker import and use shared schemas from common.db.models
```

This avoids migration conflicts between services.

---

# LLM and vector embedding

Use https://openrouter.ai as the main provider for all models. Config in `.env`

# Configuration

Each component should have:

```txt
.env
settings.yml
```

## `.env`

Used for secrets and environment-specific runtime values.

Examples:

```txt
DATABASE_URL=
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
API_BASE_URL=
REDIS_URL=
```

Also, remember to create `.env.example` as template contain all valid variables and values.

## `settings.yml`

Used for non-secret app configuration.

Examples:

```yml
app:
  name: market-watch-assistant
  environment: development

bot:
  polling_interval_seconds: 300
  default_retention_days: 60

alerts:
  default_channel: telegram
  min_immediate_score: 80
```

---

# Deployment

Use Docker Compose for local and personal production deployment.

Example services:

```txt
market-watch-bot
dashboard
```

Optional later:

```txt
redis
bot-scheduler
bot-agent-worker
bot-notifier-worker
```

Note: postgres already run in its own separate container stack, no need to setup here.

## Recommended Compose Layout

```txt
docker-compose.yml
.env
market-watch-bot/
dashboard/
```

The Market-watch Bot should run as:

```bash
uv run market-watch worker start
```

The API server should run as:

```bash
uv run market-watch server start
```

The dashboard should run as a standard React app build/server.

---

# Design Principle

Keep the system separated by responsibility:

```txt
bot_worker:
  does market monitoring work

api_server:
  manages data, configuration, and commands

dashboard:
  provides user interface

postgres:
  shared source of truth
```

The bot should be standalone, CLI-capable, and operationally independent. The dashboard and API server should control and observe it, but not host its long-running market watch logic.

# Implementation Phases guideline

Implement and fully test components in this order:
- Market-watch bot
- API Server
- Dashboard

Only build the next component after current one already working by design.
