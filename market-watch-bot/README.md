# Market Watch Backend Services

The core Python backend for the Market Watch Assistant, containing the ingestion pipelines, event clustering engine, FastAPI server, database schema, and agentic investigations.

---

## 📖 Component Documentation
Refer to these dedicated guides for detailed class boundaries, stage logs, and execution setups:
- **[Bot Worker & Ingestion Pipeline](../docs/bot_worker.md)**
- **[FastAPI API Server](../docs/api_server.md)**
- **[Database & Shared Common Layer](../docs/common.md)**
- **[Main System Overview](../docs/overview.md)**

---

## 📁 Package Layout
- **`common/`**: Databases session helper (`common.db.session`), configuration setups (`common.config`), logging layouts, LLM wraps (`common.llm`), and rss parsers.
- **`bot_worker/`**: Background worker loop, CLI command routers (`bot_worker.cli`), and service logic layer (ingestion, vector clustering, scoring, and investigations).
- **`api_server/`**: FastAPI routers, request schemas, authentication tokens middleware, and maintenance statistics.

---

## 🚀 CLI Reference & Scripts

Execution commands require the `uv` tool under the `market-watch-bot/` directory.

### Setup and Health
```bash
uv run market-watch init    # Setup .env and settings.yml
uv run market-watch migrate # Run alembic database upgrades
uv run market-watch doctor  # Verify connections and key scopes
```

### Run Pipelines
```bash
uv run market-watch pipeline run --dry-run # Dry run ingestion
uv run market-watch source list             # List configured news feeds
```

### Start Processes
```bash
uv run market-watch worker start # Start the worker run loop
uv run market-watch server start # Start the FastAPI server (port 8000)
```

### Run Tests & Checks
```bash
uv run pytest        # Run test suites
uv run ruff check .  # Lint python packages
```
