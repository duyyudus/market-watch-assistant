# Market Watch Assistant

Personal market watch system with a Python backend, React dashboard, and PostgreSQL database. It collects news signals, clusters them into events, correlates market price moves, performs agentic investigations, and sends alerts to Telegram.

---

## 📖 System Documentation
Detailed architecture, schemas, pipelines, and interface specifications are available in the `docs/` folder:
- **[Architecture & Component Overview](./docs/overview.md)**
- **[Bot Worker & Ingestion Pipeline](./docs/bot_worker.md)**
- **[FastAPI API Server](./docs/api_server.md)**
- **[React Dashboard](./docs/dashboard.md)**
- **[Database & Shared Common Layer](./docs/common.md)**

---

## 📁 Repository Layout
- **`market-watch-bot/`**: Python backend housing:
  - `bot_worker/`: CLI, ingestion pipeline, hybrid event clustering, scoring, Telegram alerts, and agentic investigations.
  - `api_server/`: FastAPI server for queries, dashboard mutations, and job triggers.
  - `common/`: SQLAlchemy database models/sessions, YAML configuration, RSS crawler, and OpenRouter LLM clients.
- **`dashboard/`**: React 19, Vite, TypeScript, and Tailwind CSS/daisyUI UI monitoring dashboard.
- **`docs/`**: Markdown system architecture documentation.

---

## 🚀 Quick Start

### 1. Run via Docker Compose
Start the database, worker, server, and dashboard containers:
```bash
docker compose up --build
```

### 2. Manual Development Setup

#### Python Backend Setup (`market-watch-bot/`):
```bash
cd market-watch-bot
uv run market-watch init    # Generate .env configuration
uv run market-watch migrate # Run database migrations
uv run market-watch doctor  # Verify services and connection health
```

Start the background worker:
```bash
uv run market-watch worker start
```

Start the FastAPI development server (defaults to port `8000`):
```bash
uv run market-watch server start --reload
```

#### React Dashboard Setup (`dashboard/`):
```bash
cd dashboard
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.
