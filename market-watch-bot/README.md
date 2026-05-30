# Market Watch Assistant - Core Services

This repository houses the core Python backend services for the Personal Market Watch Assistant, organized into three parallel packages under a single virtual environment:

1. **`common/`**: The shared core layer, including database schemas (`common.db.models`), session management (`common.db.session`), central logging (`common.logging`), and application configuration parsing (`common.config`).
2. **`bot_worker/`**: The background worker service CLI, event pipelines, scoring engines, investigation utilities, and Alert/Digest delivery channels.
3. **`api_server/`**: The FastAPI control and data access layer, implementing schemas, services, and route endpoints to serve dashboard requests.

---

## Quick start

### Database and Configuration Setup
```bash
# Initialize environments and copy settings.yml
uv run market-watch init

# Verify system doctor status
uv run market-watch doctor

# Run database migrations
uv run market-watch migrate
```

### Ingestion & Pipeline Jobs
```bash
# List loaded sources
uv run market-watch source list

# Trigger a dry-run ingestion & clustering pipeline run
uv run market-watch pipeline run --dry-run
```

### Running the Background Worker
The background worker executes scheduled ingestion, clustering, and alert delivery pipelines. To start the worker process:
```bash
# Start the worker loop in the foreground
uv run market-watch worker start
```

### Running the API Server
The API server is fully integrated into the main CLI. To start the FastAPI application:
```bash
# Start the API server on default port 8000
uv run market-watch server start

# Start the API server with auto-reload (for development)
uv run market-watch server start --port 8000 --reload
```

