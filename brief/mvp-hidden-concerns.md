# Market Watch Assistant MVP — Hidden Concerns Audit

> [!NOTE]
> This document is a comprehensive review of the current MVP codebase, focused on identifying potential hidden risks, architectural concerns, and operational pitfalls that could become real problems as usage scales or the system moves toward 1.0.

---

## 1. Security & Access Control

### 1.1 API Server Has Zero Authentication (🔴 High)

**Affected files**: [main.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/main.py), all routers under [api/routers/](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/api/routers)

The FastAPI application has no authentication or authorization. Any client that can reach the server can:
- Queue arbitrary bot commands (`POST /bot/commands`) including `pipeline.run`, `retention.run`, and `alert.dispatch`
- Modify sources, watchlist entries, and alert policy settings
- Trigger destructive operations like retention cleanup

While this is acceptable for a personal LAN-only tool, the CORS regex already allows `10.x.x.x` and `192.168.x.x` ranges — meaning any device on the local network can mutate the system.

**Remediation**: Add at minimum a static API key / bearer token gate before 1.0, especially if exposing over VPN or public networks.

### 1.2 Secrets Exposed in Default Config (🟡 Medium)

**Affected files**: [config.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/common/config.py#L13-L15)

```python
DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@192.168.100.39:5432/market_watch_assistant"
)
```

The default database URL contains literal credentials (`postgres:postgres`) and a LAN IP address. If the repo is forked or the config module is imported in unexpected contexts, these leak.

**Remediation**: Change the default to something clearly non-functional (e.g. `postgresql+asyncpg://user:password@localhost:5432/market_watch_assistant`) and require `.env` for real credentials.

### 1.3 Telegram Bot Token in Memory (🟢 Low)

**Affected files**: [alert_delivery.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/alert_delivery.py#L96-L112)

The Telegram bot token is passed as a plain string in `AlertDeliveryConfig`. If the process crashes and core-dumps, or if debug logging is enabled, the token could leak. This is minor for a personal tool but worth noting.

---

## 2. Database & Data Integrity

### 2.1 API Server Sessions Never Auto-Commit on Failure (🟡 Medium)

**Affected files**: [api_server/app/db/session.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/db/session.py), API service layer

The API `get_session` yields a session but never wraps it in `session.begin()`. Individual service methods call `await session.commit()` explicitly. If an unhandled exception occurs after a partial mutation (e.g., after adding a source but before committing), the session silently rolls back — which is fine — but there's no middleware ensuring consistent commit/rollback behavior across all routes. Partial writes are unlikely but possible if a commit fails midway.

**Remediation**: Wrap the session dependency in a `begin()` / auto-commit pattern or add FastAPI middleware for transaction management.

### 2.2 Bot Worker Session Scope Creates a New Engine Per Call (🔴 High)

**Affected files**: [common/db/session.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/common/db/session.py#L10-L15)

```python
def make_engine(settings: Settings):
    return create_async_engine(settings.database_url, pool_pre_ping=True)

def make_session_factory(settings: Settings):
    return async_sessionmaker(make_engine(settings), expire_on_commit=False)
```

Every call to `make_session_factory()` creates a brand-new `AsyncEngine` with its own connection pool. In the worker loop, `_with_session` is called every tick (every 2 seconds), meaning the worker creates a new engine + connection pool 1,800 times per hour. This causes:
- Connection pool exhaustion under sustained load
- Stale connections accumulating on the Postgres side
- Gradual memory creep from abandoned engine objects

**Remediation**: Cache the engine and session factory at module or application level, keyed by database URL.

### 2.3 Retention Deletion Order May Violate Foreign Keys (🟡 Medium)

**Affected files**: [retention.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/retention.py#L119-L161)

`run_retention` deletes from tables like `raw_news_items`, `normalized_news_items`, and `event_clusters` by time-based cutoffs. However, child tables (`news_item_embeddings`, `event_cluster_items`, `event_cluster_embeddings`, `news_entities`, `alert_decisions`, `event_score_history`) aren't explicitly cleaned before their parents. This relies on Postgres `CASCADE` or `SET NULL` foreign key constraints being present in the migration, which should be verified. If those cascades are missing, retention will fail with FK constraint violations.

**Remediation**: Verify migration FK constraints have `ON DELETE CASCADE` or explicitly delete child rows first.

### 2.4 Deduplication Is In-Memory Only (🟡 Medium)

**Affected files**: [ingestion.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/ingestion.py#L103-L116)

```python
async def mark_exact_duplicates(session: AsyncSession) -> int:
    stmt = select(NormalizedNewsItem).where(NormalizedNewsItem.processing_status == "normalized")
    items = list((await session.scalars(stmt)).all())
    seen: set[tuple[str | None, str]] = set()
```

All `normalized` items are loaded into memory for dedup. As the dataset grows, this could become a memory issue. More importantly, the `seen` set is rebuilt from scratch each run, so the "first wins" semantics depend on the order of the query (which has no `ORDER BY`).

**Remediation**: Add a unique constraint or use a database-level dedup query to avoid loading the entire table.

### 2.5 No Database Indexes on Hot Query Paths (🟡 Medium)

The data model has no explicit indexes beyond primary keys and the one unique constraint per table. Queries like:
- `NormalizedNewsItem.processing_status == "normalized"` (used every pipeline tick)
- `EventCluster.last_updated_at >= cutoff` (vector search)
- `BotCommand.status == "pending"` (polled every 2 seconds)
- `AlertDecisionRecord.sent_at.is_(None)` (alert dispatch)
- `AgentInvestigation.status == "pending"` (investigation queue)

These will degrade to sequential scans as tables grow. The `BotCommand` table is polled with `FOR UPDATE SKIP LOCKED` every 2 seconds — without an index on `status`, this becomes expensive quickly.

**Remediation**: Add targeted indexes on `processing_status`, `status`, `sent_at`, and `last_updated_at` columns.

---

## 3. Resilience & Error Handling

### 3.1 No Retry Logic for External API Calls (🔴 High)

**Affected files**: [sources.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/sources.py#L359-L406), [market.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/market.py#L41-L110), [alert_delivery.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/alert_delivery.py#L96-L112)

HTTP calls to RSS feeds, CoinGecko, Binance, Yahoo Finance, Vietnam stock API, Telegram, Brave Search, and OpenRouter are all single-shot with a 20-second timeout. There is zero retry logic, exponential backoff, or rate limiting anywhere in the codebase. A transient network hiccup causes:
- Source fetches to be marked as `failed` permanently (until next poll)
- Market moves to be skipped entirely for that pipeline run
- Telegram alerts to be marked `failed` with no automatic retry
- LLM/embedding calls to fail and be left in `failed` status

**Remediation**: Add `tenacity` or `httpx`-level retry with exponential backoff. For Telegram alerts especially, failed deliveries should be retried on the next dispatch cycle.

### 3.2 No Rate Limiting on External APIs (🟡 Medium)

CoinGecko (free tier: ~10-30 req/min), Binance, and Yahoo Finance all have rate limits. The worker fetches sequentially but has no explicit rate awareness. If the watchlist grows to 20+ crypto symbols, CoinGecko's free tier will start rejecting requests.

**Remediation**: Add per-provider rate limiters (e.g., `asyncio.Semaphore` with delays) and handle 429 responses gracefully.

### 3.3 Pipeline Stage Failures Can Silently Cascade (🟡 Medium)

**Affected files**: [pipeline.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/pipeline.py#L54-L265)

If embedding generation fails (Stage 5/7), the pipeline continues to clustering (Stage 6), which depends on embeddings for vector-based cluster attachment. The pipeline logs an error but doesn't report which downstream stages were degraded.

Similarly, if entity extraction (Stage 4) fails, clustering uses watchlist-based entity matching instead of LLM-extracted entities, silently producing lower-quality clusters with no indication in the returned stats.

**Remediation**: Track stage health and add a `degraded_stages` field to the pipeline result so operators know which stages ran in fallback mode.

### 3.4 Worker Crash Leaves Commands in "Running" State Forever (🟡 Medium)

**Affected files**: [bot_commands.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/bot_commands.py#L58-L73)

`claim_pending_bot_command` marks a command as `running` and flushes. If the worker crashes during execution, that command stays as `running` forever — it's never picked up again and never marked as failed. There's no timeout or heartbeat mechanism.

**Remediation**: Add a stale-command reaper that marks `running` commands older than N minutes as `failed`, or implement a `claimed_at` + timeout pattern.

---

## 4. Resource & Performance Management

### 4.1 Market Data Fetch Creates New HTTP Client Per Symbol (🟡 Medium)

**Affected files**: [market.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/market.py#L63)

Actually, the code uses a single `httpx.AsyncClient` context manager, which is good — but within that context, crypto fetches for non-USDT symbols fall back from Binance to CoinGecko sequentially. If the Binance call raises a non-HTTP error (e.g., JSON parse error), the fallback won't trigger because only `httpx.HTTPError` is caught.

### 4.2 Dashboard Loads All Resources on Every Refresh (🟡 Medium)

**Affected files**: [App.tsx](file:///home/duyyudus/git/market-watch-assistant/dashboard/src/app/App.tsx#L51-L102)

The `load()` function fires 10 parallel API calls every time the user clicks "Refresh" or the app mounts. There's no caching, debouncing, or stale-while-revalidate strategy. If the API server is slow, the UI blocks entirely until all 10 settle.

**Remediation**: Add per-resource caching with TTL, or use a data-fetching library like `react-query` / `swr`.

### 4.3 Vector Search Uses Raw SQL Without Parameterized Casting (🟢 Low)

**Affected files**: [events.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/events.py#L65-L97)

The vector similarity query uses `sql_text()` with bound parameters, which is safe from injection. However, the `pgvector_literal()` function manually formats the vector as a string. While this works correctly, it bypasses SQLAlchemy's type system. If `embedding.vector` ever contains non-float values, it would produce invalid SQL rather than a clean error.

---

## 5. Architectural Coupling

### 5.1 `bot_worker` and `api_server` Share `bot_worker.db.models` (🟡 Medium)

**Affected files**: [api_server/app/schemas/](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/schemas), [bot_worker/db/models.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/db/models.py)

The `bot_worker/db/models.py` re-exports from `common/db/models.py`, which is correct. But the API server's schemas and services import from `bot_worker.db.models` in at least some paths, and the API schemas module has its own "common" definitions. This means the API server has an import dependency on `bot_worker`, which contradicts the architectural goal of keeping them decoupled.

### 5.2 Settings Loaded at Module Import Time in API Server (🟡 Medium)

**Affected files**: [api_server/app/main.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/main.py#L9), [api_server/app/db/session.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/api_server/app/db/session.py#L9-L11)

Both `main.py` and `db/session.py` call `load_settings()` at module import time. This means:
- Settings can't be overridden for testing without monkeypatching
- If `.env` or `settings.yml` is missing/corrupt, the import itself fails with an unclear traceback
- The engine is created before the app starts, preventing configuration injection

### 5.3 `__all__` Export in services/__init__.py Lists Non-Existent Symbol (🟢 Low)

**Affected files**: [services/__init__.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/__init__.py#L152)

```python
"run_move_investigation",
```

This symbol is listed in `__all__` but not imported at the top of the file. If any code does `from bot_worker.services import run_move_investigation` via `__all__`, it will raise an `ImportError`.

---

## 6. Operational Gaps

### 6.1 No Docker Compose File Exists (🟡 Medium)

The project brief specifies Docker Compose for deployment, but no `docker-compose.yml`, `Dockerfile`, or container definition exists anywhere in the repo. The system can only be run via manual `uv run` commands.

### 6.2 No Graceful Shutdown in Worker Loop (🟡 Medium)

**Affected files**: [worker.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/cli/worker.py#L77-L99)

The worker loop runs forever with `while True` / `asyncio.sleep`. There's no signal handler for `SIGTERM`/`SIGINT` to:
- Finish the current pipeline stage cleanly
- Flush pending database writes
- Mark in-flight commands as failed

A `Ctrl+C` or process kill during a database write could leave partial state.

### 6.3 No Health Check Endpoint Beyond Bot Status (🟢 Low)

The API has `/bot/status` but no lightweight `/health` or `/ready` endpoint that simply returns 200 — useful for monitoring, load balancers, and container orchestration.

### 6.4 Log Rotation Counts Lines Per-Emit After Rollover (🟢 Low)

**Affected files**: [logging.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/common/logging.py#L59-L68)

The `LineRotatingFileHandler.emit()` method calls `self.format(record)` after `super().emit(record)` to count newlines. This means the formatted output is generated twice — once by `super().emit()` and once for the line count. This is a minor performance issue with no correctness impact.

---

## 7. Testing & Code Quality

### 7.1 No Integration Tests Against Real Database (🟡 Medium)

All 21 test files use in-memory SQLite with the JSONB-to-JSON compiler shim. This means:
- `pgvector` operations are never tested
- `FOR UPDATE SKIP LOCKED` (used in command claiming) is untested against real locking
- PostgreSQL-specific JSON operators (`@>`, `?`, `contains`) are untested
- `ON CONFLICT DO NOTHING` with `index_elements` behaves differently in SQLite

### 7.2 No Dashboard E2E Tests (🟡 Medium)

The dashboard has unit tests ([App.test.tsx](file:///home/duyyudus/git/market-watch-assistant/dashboard/src/App.test.tsx)) but no end-to-end tests with a browser runner (Playwright, Cypress). User flows like "create a source → verify it appears in the list → enable/disable it" are untested.

### 7.3 Hardcoded Watchlist Tier "A" in Scoring Logic (🟡 Medium)

**Affected files**: [events.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/events.py#L126-L127), [alerts.py](file:///home/duyyudus/git/market-watch-assistant/market-watch-bot/bot_worker/services/alerts.py#L54)

```python
watchlist_tier="A" if cluster.affected_entities else None,
```

The scoring system supports tiers S/A/B/C/D with different relevance scores, but every cluster that has any affected entity is always scored as tier "A". The actual tier from the watchlist entity is never looked up. This means tier-based prioritization doesn't actually work.

---

## Summary Matrix

| Area | Issue | Severity |
|------|-------|----------|
| Security | No API authentication | 🔴 High |
| Database | New engine per session call in worker | 🔴 High |
| Resilience | No retry logic for external APIs | 🔴 High |
| Database | Default URL has literal credentials | 🟡 Medium |
| Database | API sessions lack transaction wrapper | 🟡 Medium |
| Database | Retention FK cascade not verified | 🟡 Medium |
| Database | In-memory-only dedup may not scale | 🟡 Medium |
| Database | Missing indexes on hot query columns | 🟡 Medium |
| Resilience | No rate limiting on external APIs | 🟡 Medium |
| Resilience | Pipeline stage failures cascade silently | 🟡 Medium |
| Resilience | Crashed commands stuck in "running" | 🟡 Medium |
| Performance | Dashboard loads all resources at once | 🟡 Medium |
| Architecture | API server imports from bot_worker | 🟡 Medium |
| Architecture | Settings loaded at import time | 🟡 Medium |
| Operations | No Docker Compose exists | 🟡 Medium |
| Operations | No graceful worker shutdown | 🟡 Medium |
| Testing | No real-DB integration tests | 🟡 Medium |
| Testing | No dashboard E2E tests | 🟡 Medium |
| Scoring | Watchlist tier always hardcoded to "A" | 🟡 Medium |
| Security | Telegram token in plain memory | 🟢 Low |
| Architecture | `__all__` lists non-existent export | 🟢 Low |
| Operations | No lightweight health endpoint | 🟢 Low |
| Operations | Log handler formats output twice | 🟢 Low |
| Database | Vector literal bypasses type system | 🟢 Low |
