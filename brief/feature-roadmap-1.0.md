# Market Watch Assistant — 1.0 Feature Roadmap

> [!NOTE]
> This document proposes feature sets and improvements for the next development sprint, organized into prioritized development tracks. Features are grouped by component area and ordered by impact-to-effort ratio.

---

## Track 1: Infrastructure & Deployment

These are foundational improvements that other tracks depend on. **Tackle first.**

### 1.1 Docker Compose Stack (Priority: P0)

The brief specifies Docker Compose but none exists. Create a full production-ready stack:

```
services:
  bot-worker:    # uv run market-watch worker start
  api-server:    # uv run market-watch server start
  dashboard:     # nginx serving built React app
```

**Key decisions**:
- Single `Dockerfile` with multi-stage build (one base, multiple targets) or separate Dockerfiles per service
- Healthcheck definitions for each service. The API already has a lightweight `/health`
  endpoint; add a DB-backed `/ready` endpoint or equivalent readiness check for containers.
- Volume mounts for `.env`, `settings.yml`, and `.log/`
- `depends_on` with healthcheck conditions

### 1.2 API Authentication Layer (Priority: P0)

Add bearer-token or API-key authentication:
- Static API key from `.env` (`API_AUTH_TOKEN`) validated via FastAPI middleware
- Dashboard sends the token via `Authorization: Bearer <token>` header
- All mutating endpoints (`POST`, `PATCH`, `DELETE`) require auth
- Read-only endpoints can optionally stay open for monitoring

### 1.3 Database Connection Pooling Fix (Priority: P0)

Fix the bot worker's session factory to reuse a single engine:
- Create engine once at startup, cache it
- Pass the session factory down through the worker loop
- Add connection pool metrics (pool size, overflow, checkedout)

### 1.4 Database Index Migration (Priority: P0)

Add a new Alembic migration (`0008_performance_indexes.py`) with indexes on:
- `bot_commands(status, created_at)` — polled every 2 seconds
- `normalized_news_items(processing_status)` — queried every pipeline run
- `alert_decisions(sent_at)` — alert dispatch query
- `agent_investigations(status, created_at)` — investigation queue
- `event_clusters(last_updated_at)` — vector search cutoff
- `job_runs(started_at DESC)` — status display

### 1.5 Secure Configuration & Decoupled Secrets (Priority: P1)

Address low-to-medium security and configuration issues:
- Remove hardcoded LAN fallback credentials (`postgres:postgres@192.168.100.39`) from `common/config.py`. Enforce strict environment variables configuration via `.env` files.
- Load the Telegram bot token strictly from environment-backed settings, redact it from logs,
  command output, provider responses, and error diagnostics, and avoid persisting it outside
  runtime configuration.

### 1.6 Deferred Settings Loading (Priority: P1)

De-couple setting load from import-time in `api_server` and `common/config.py`:
- Load configuration dynamically using standard FastAPI dependency injection (`get_settings`) instead of performing side-effects at import time in `main.py` and `db/session.py`.
- This ensures settings can be easily overridden during tests and prevents startup failures with obscure tracebacks.

---

## Track 2: Pipeline Intelligence

Improvements to the core data processing pipeline that increase signal quality.

### 2.1 Retry & Backoff for External APIs (Priority: P0)

Add retry logic with exponential backoff to all external HTTP calls:
- RSS source fetching: retry 2x with 5s/15s delays
- Market data APIs: retry 2x with rate-limit-aware backoff (handle 429)
- LLM/embedding APIs: retry 1x with 30s delay
- Telegram delivery: retry 3x with 10s/30s/60s delays
- Brave Search: retry 1x

Use `tenacity` library or build a thin `httpx` transport-level retry.

### 2.2 Per-Provider Rate Limiting & 429 Cooldowns (Priority: P1)

Make external API usage rate-aware instead of only retry-aware:
- Add provider-specific request budgets for CoinGecko, Binance, Yahoo Finance, Vietnam market API, RSS feeds, Brave Search, Telegram, OpenRouter chat completions, and OpenRouter embeddings.
- Handle `429` and provider throttle responses by recording a cooldown window and skipping non-critical calls until the cooldown expires.
- Surface rate-limit skips in pipeline/job results so operators can distinguish provider throttling from empty data.

### 2.3 Actual Watchlist Tier-Based Scoring (Priority: P1)

Currently, all events with affected entities are scored as tier "A" regardless of the actual watchlist tier. Fix the scoring flow:

1. When building event candidates, look up the matched watchlist entries and keep the highest tier
2. Pass the actual tier (S/A/B/C/D) through to `score_event()`
3. This makes tier-based prioritization actually work: S-tier entities (e.g., BTC, SPY) will score higher than D-tier ones

### 2.4 Digest Generation & Delivery (Priority: P1)

The brief mentions digests, and infrastructure exists (`digest_preview`, `digest_display_headline`), but there's no actual digest generation or delivery:

- **Daily digest builder**: Aggregate events from the past 24h that scored above `digest_threshold`
- **Digest template**: Format a compact Telegram message grouping events by region/asset class
- **Scheduled delivery**: Add a `digest.send` bot command and schedule it in the worker loop (e.g., 8 AM ICT daily)
- **Digest history**: Store generated digests in a new `digests` table with content, delivery status

### 2.5 Multi-Source Confirmation Boosting (Priority: P1)

When the same event is reported by multiple high-quality sources (e.g., Reuters + Bloomberg), the scoring should receive a stronger confirmation boost. Currently, `source_count` increases the confidence score linearly, but doesn't differentiate between 3 reports from low-quality blogs vs. 2 from tier-1 outlets.

Add a `unique_high_quality_source_count` to `ScoreInput` and boost events with diverse high-quality coverage.

### 2.6 Smart Polling Intervals (Priority: P2)

Currently all sources are polled every pipeline run (every 5 minutes). Implement per-source polling awareness:

- Track `last_fetched_at` per source and skip sources whose `polling_interval_seconds` hasn't elapsed
- Allow "burst mode" where a source that just returned new items is polled more frequently for the next 30 minutes
- Skip sources that have had 3+ consecutive failures (backoff), with auto-resume after a cooldown

### 2.7 Web Crawler / Full-Text Extraction (Priority: P2)

RSS feeds only provide titles and snippets. For higher-quality entity extraction and event analysis:
- Add a lightweight full-text extractor using `newspaper3k`, `readability-lxml`, or `trafilatura`
- Fetch full article content for high-scoring or single-source events
- Store in `NormalizedNewsItem.raw_content` (column already exists but unused)
- Feed full text into LLM analysis for better summaries

### 2.8 Embedding-Based Cross-Language Clustering (Priority: P3)

Vietnamese-language sources produce news items that can't be title-matched with English sources. Since embeddings are language-agnostic (text-embedding-3-large handles multilingual), the vector-based cluster attachment should already work — but entity extraction from Vietnamese titles is likely poor with the current English-focused LLM prompts.

- Add Vietnamese-aware entity extraction prompts
- Test cross-language cluster attachment quality
- Add language detection metadata to guide prompt selection

### 2.9 Robust Market Data Fetch Error Handling (Priority: P1)

Improve exception safety when fetching crypto symbols and stock prices:
- Correct the sequential fallback from Binance to CoinGecko in `bot_worker/services/market.py`.
- Catch all JSON parse errors, decoding failures, and non-HTTP anomalies (instead of just catching `httpx.HTTPError`) to prevent partial fetch crashes and guarantee fallback triggers cleanly.

### 2.10 Pipeline Degradation Reporting (Priority: P1)

Make fallback mode visible in returned pipeline stats and job history:
- Add `degraded_stages` and `failed_stages` fields to pipeline results.
- Mark embedding failures, LLM entity extraction failures, market fetch failures, investigation failures, rate-limit skips, and alert dispatch failures explicitly.
- Show downstream impact in operator-facing results, especially when clustering falls back from embedding/entity signals to weaker watchlist/title matching.

### 2.11 Type-Safe Vector SQL Parameterized Casting (Priority: P2)

Address type safety around similarity searching:
- Refactor the raw `pgvector_literal()` serialization in `bot_worker/services/events.py` to use fully typed parameterized structures.
- Ensure that passing invalid arrays will cause clean validations in Python rather than generating malformed SQL.

### 2.12 Dead Exports Cleanup (Priority: P3)

Address import stability:
- Remove the nonexistent `run_move_investigation` symbol from the `__all__` list in `services/__init__.py` to eliminate potential `ImportError` bugs.

---

## Track 3: Alert & Delivery

### 3.1 Alert Channel Abstraction (Priority: P1)

Currently only Telegram and log channels are supported, with Telegram hardcoded in the delivery logic. Abstract into a channel system:

- **Channel registry**: `AlertChannel` model with type (telegram, email, webhook, slack), config (token/URL), and enabled flag
- **Channel-specific formatters**: Each channel formats the alert differently (Telegram markdown, email HTML, webhook JSON)
- **Webhook channel**: POST alert JSON to a configurable URL — enables integration with Discord, Slack, or custom systems
- Dashboard UI for managing alert channels

### 3.2 Alert Suppression Rules (Priority: P1)

Add user-configurable suppression:
- **Cooldown period**: Don't re-alert on the same event cluster within N hours
- **Region filter**: Only alert on specific regions (e.g., suppress "global_macro" alerts on weekends)
- **Quiet hours**: No immediate alerts between 11 PM - 7 AM ICT (queue for morning digest instead)
- **Entity-level mute**: Temporarily mute alerts for a specific ticker/entity

### 3.3 Alert Acknowledgement Flow (Priority: P2)

Track whether the user has seen/acknowledged each alert:
- Add `acknowledged_at` to `AlertDecisionRecord`
- Dashboard shows unacknowledged alert count as a badge
- Telegram could use inline keyboard buttons for ack/dismiss

### 3.4 Failed Alert Retry Queue (Priority: P1)

Currently, failed Telegram deliveries are logged but never retried. Add a retry mechanism:
- On next `alert.dispatch` cycle, re-attempt deliveries with `status = "failed"` and `attempted_at` older than 5 minutes
- Max 3 retries per delivery, then mark as `permanently_failed`

---

## Track 4: Dashboard & UX

### 4.1 Real-Time Updates via WebSocket / SSE (Priority: P1)

The dashboard currently requires manual refresh. Add server-sent events (SSE) for live updates:
- API server endpoint: `GET /events/stream` using FastAPI's `StreamingResponse`
- Events to stream: new alert fired, pipeline completed, command status changed
- Dashboard subscribes on mount and updates state incrementally

### 4.2 Event Detail View & Timeline (Priority: P1)

The events page shows a list, but clicking an event should reveal:
- Full event timeline: when it was first seen, each news item that was clustered, score changes over time
- LLM analysis details: summary, event type, impact rationale, risk flags
- Investigation results: evidence gathered, official confirmations, suggested actions
- Related market moves: price/volume changes in affected tickers
- Action buttons: mark status, trigger investigation, rescore

### 4.3 Source Health Dashboard (Priority: P1)

A dedicated view showing per-source operational health:
- Last fetch time, success/failure streak, average latency
- Sparkline chart of items fetched over the past 7 days
- Color-coded status: green (healthy), yellow (degraded), red (failing)
- Quick action: test fetch, enable/disable, edit settings

### 4.4 Scoring Explanation Panel (Priority: P2)

For each event, show a visual breakdown of how its score was calculated:
- Bar chart showing each scoring component (source, impact, relevance, novelty, urgency, market move)
- Penalty indicators (duplicate, stale, noise)
- LLM modifier with rationale
- Investigation modifier with evidence summary

### 4.5 Auto-Refresh with Polling (Priority: P2)

Before SSE is available, add a configurable auto-refresh interval:
- Toggle in the header: "Auto-refresh: off / 30s / 60s / 5m"
- Use `setInterval` with the existing `load()` function
- Persist preference in `localStorage`

### 4.6 Mobile-Responsive Layout (Priority: P2)

The dashboard has a mobile dropdown nav selector but the content areas (tables with many columns, grid layouts) aren't optimized for small screens:
- Card-based views for events and alerts on mobile
- Collapsible table columns
- Bottom navigation bar instead of dropdown

### 4.7 Dark/Light Mode Persistence & System Preference (Priority: P3)

Theme persistence already works via `localStorage`, but there's no "system" option that follows `prefers-color-scheme`. Add a third theme option that auto-switches.

### 4.8 Client-Side API Request Caching & Debouncing (Priority: P1)

Prevent the UI from choking under high loads or slow network speeds:
- Introduce a data-fetching and caching manager (such as `react-query`, `swr`, or custom React hooks with a TTL cache) for API resources.
- Stop loading all 10 resources in parallel on every component mount or tab switch; implement smart client-side caching and debounced API requests to ensure a fluid user experience.

---

## Track 5: Observability & Operations

### 5.1 Structured Logging with JSON Output (Priority: P1)

Replace the current line-based log format with structured JSON logging:
- Each log line is a JSON object with `timestamp`, `level`, `logger`, `message`, and contextual fields
- Pipeline stages include `stage_name`, `duration_ms`, `items_processed`
- LLM calls include `model`, `prompt_version`, `tokens_used`, `latency_ms`
- This enables log aggregation and querying via tools like `jq`, Loki, or CloudWatch

### 5.2 Pipeline Metrics & Performance Tracking (Priority: P1)

Track per-stage timing and throughput:
- `PipelineRunMetrics` dataclass with per-stage `start_time`, `end_time`, `items_in`, `items_out`
- Store in the `JobRun.result` JSON
- Dashboard shows pipeline performance trends over time
- Alert if any stage takes >2x its average duration

### 5.3 LLM Cost Tracking Dashboard (Priority: P1)

The `LLMAnalysisRun` model already stores `usage` with token counts. Build a dashboard panel showing:
- Total tokens consumed per day/week
- Cost estimate based on model pricing
- Breakdown by analysis type (entity extraction, event enrichment, investigation, cluster decision)
- Trend chart over time

### 5.4 Stale Command Reaper (Priority: P1)

Add to the worker tick: if any `BotCommand` has `status = "running"` and `started_at` older than 10 minutes, mark it as `failed` with reason "timed out (worker restart?)". This prevents commands from being stuck forever after crashes.

### 5.5 Graceful Worker Shutdown (Priority: P1)

Add signal handlers:
```python
async def loop():
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)
    while not shutdown.is_set():
        # ... tick
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            continue
```

### 5.6 Operational Alerts (Self-Monitoring) (Priority: P2)

The bot monitors markets — but who monitors the bot? Add self-monitoring:
- If no pipeline run has completed in 2x the polling interval, send a Telegram alert: "⚠️ Market Watch worker appears to be down"
- If >50% of sources are failing, alert: "⚠️ Multiple source fetch failures"
- If LLM API key is expired/invalid (3+ consecutive failures), alert: "⚠️ LLM provider unreachable"

This could be a lightweight "watchdog" that runs alongside or as part of the worker.

### 5.7 Log Rotator Double Formatting Fix (Priority: P3)

Fix log performance:
- Optimize `LineRotatingFileHandler.emit()` in `common/logging.py` so that it doesn't double-call `self.format(record)`. Generate the log format once and reuse the value for counting newlines during rollover calculation.

---

## Track 6: Data Quality & Scale

### 6.1 Database-Level Deduplication (Priority: P1)

Replace the in-memory dedup with a database-level approach:
- Add a unique partial index on `(canonical_url_hash, title_hash)` where `processing_status = 'normalized'`
- Or use a `SELECT ... WHERE EXISTS` anti-join query instead of loading all items
- This scales to millions of rows without memory issues

### 6.2 Source Quality Auto-Scoring (Priority: P2)

Currently `source_score` is manually set. Add automatic quality signals:
- **Reliability score**: % of successful fetches over the past 30 days
- **Freshness score**: average delay between `published_at` and `fetched_at`
- **Duplicate rate**: % of items from this source that get deduped
- **Event contribution**: % of items that end up in event clusters
- Combine into an auto-calculated quality metric that modulates the static `source_score`

### 6.3 Incremental RSS Polling with ETags / Last-Modified (Priority: P2)

RSS feeds support conditional requests. Store the `ETag` and `Last-Modified` headers from the previous fetch and send them on the next request via `If-None-Match` / `If-Modified-Since`. If the server returns `304 Not Modified`, skip parsing entirely. This reduces bandwidth and processing load.

### 6.4 Event Merge/Split Operations (Priority: P2)

Sometimes the clustering algorithm creates two clusters for the same event, or merges distinct events. Add:
- **Merge**: Combine two event clusters into one, reassigning all news items and recalculating scores
- **Split**: Move selected news items from one cluster into a new cluster
- Both via CLI commands and dashboard UI

### 6.5 Archived Event Compaction (Priority: P3)

Events older than 30 days with `archive_only` alert level are rarely accessed. Compact them:
- Store a JSON summary in the cluster row
- Drop their embeddings and entity associations
- Keep the cluster and alert decision for historical reporting
- This reduces storage without losing the audit trail

### 6.6 Configurable Embedding Dimensions (Priority: P3)

The embedding dimension is hardcoded to 1536 in the `Vector(1536)` column type. If a different model with different dimensions is desired (e.g., 768-dim for cost savings), a migration and column type change is required. Consider:
- Storing dimension metadata alongside the vector
- Or using a more flexible storage approach for embeddings

### 6.7 Database Retention Integrity Fix (Priority: P1)

Address integrity on retention sweeps:
- Audit Alembic migrations (`market-watch-bot/alembic/versions/`) and current model FKs for parent tables deleted by retention.
- Add `ON DELETE CASCADE` / `SET NULL` behavior where it preserves intended history, or change `run_retention()` to delete child rows before parent rows.
- Cover child tables such as `news_item_embeddings`, `event_cluster_items`, `event_cluster_embeddings`, `news_entities`, `alert_decisions`, and `event_score_history` so retention cannot crash on FK violations.

---

## Track 7: Architecture, Quality & Testing

These tasks focus on long-term safety, decoupling components, and solid testing frameworks.

### 7.1 API Transaction Middleware & Safety (Priority: P0)

Ensure transactional consistency across the API server:
- Refactor `get_session` in `api_server/app/db/session.py` to use a transactional context manager (or middleware) that automatically rolls back when an unhandled exception occurs and commits consistently on success.
- Eliminate explicit `await session.commit()` calls inside business services where possible, keeping route scopes cleanly transaction-isolated.

### 7.2 Codebase Decoupling (Priority: P1)

Improve architectural separation:
- Eliminate direct imports of `bot_worker` modules inside the `api_server` code tree.
- Specifically remove the current `api_server/app/schemas/bot.py` dependency on `bot_worker.services.bot_commands` for command constants and payload validation rules.
- Move shared command contracts to `common/` or keep them API-owned while preserving the worker/API boundary through Postgres command records.

### 7.3 Real-Database Integration Testing Stack (Priority: P1)

Eliminate SQLite testing discrepancies:
- Enable integration testing against a real local PostgreSQL container with the `pgvector` extension instead of relying on pure SQLite in-memory shims.
- Ensure that pgvector features, database locks (`FOR UPDATE SKIP LOCKED`), and custom PostgreSQL JSON operators are fully covered by pytest suites.

### 7.4 Dashboard End-to-End (E2E) Test Suite (Priority: P2)

Secure the web user interface:
- Set up an automated testing stack (using Playwright or Cypress) to run E2E browser tests on key user dashboard flows (e.g., enabling/disabling sources, modifying watchlist items, acknowledging alerts, triggering manual runs).

---

## Prioritized Development Plan

| Development Track | Feature & Tasks | Priority | Key Deliverable / Objective |
| :--- | :--- | :---: | :--- |
| **Track 1: Infrastructure & Deployment** | 1.1 Docker Compose Stack | P0 | Multi-stage orchestration base for server, worker, and proxy |
| | 1.2 API Authentication Layer | P0 | Secure token validation middleware on mutating endpoints |
| | 1.3 Database Connection Pooling Fix | P0 | Single persistent `AsyncEngine` cached at worker startup |
| | 1.4 Database Index Migration | P0 | Indexing on critical columns (`status`, `processing_status`, `sent_at`) |
| | 1.5 Secure Config & Decoupled Secrets | P1 | Enforced local env secrets management, no hardcoded LAN strings |
| | 1.6 Deferred Settings Loading | P1 | Dynamic config fetching via FastAPI dependency injection |
| **Track 2: Pipeline Intelligence** | 2.1 Retry & Backoff for External APIs | P0 | Tenacity-driven backoff logic for external feeds, exchange, and LLM |
| | 2.2 Per-Provider Rate Limiting & 429 Cooldowns | P1 | Provider request budgets and cooldown visibility for throttled APIs |
| | 2.3 Actual Watchlist Tier Scoring | P1 | S-to-D-tier priority-based calculations using watchlist models |
| | 2.4 Digest Generation & Delivery | P1 | Automated morning Telegram newsletter construction |
| | 2.5 Multi-Source Confirmation Boosting | P1 | Dynamic scoring boosts for high-quality cross-outlet verification |
| | 2.9 Robust Market Data Error Fallbacks | P1 | Safe JSON and non-HTTP parsing failover routines |
| | 2.10 Pipeline Degradation Reporting | P1 | `degraded_stages` and `failed_stages` persisted in pipeline results |
| | 2.6 Smart Polling Intervals | P2 | Cooldowns, skipping, and dynamic polling rates for news feeds |
| | 2.7 Web Crawler / Full-Text Extraction | P2 | Scraping full article texts to feed high-quality LLM prompts |
| | 2.11 Type-Safe Vector SQL Parameterized Casting | P2 | Typed binding arrays instead of custom string casting scripts |
| | 2.8 Embedding-Based Cross-Language Clustering | P3 | Language detection logic with Vietnamese entity parsing fallback |
| | 2.12 Dead Exports Cleanup | P3 | Eliminates invalid `run_move_investigation` symbol export |
| **Track 3: Alert & Delivery** | 3.4 Failed Alert Retry Queue | P1 | Background dispatch retry loop for dropped Telegram messages |
| | 3.2 Alert Suppression Rules | P1 | Custom quiet hours, cooldown windows, and asset-specific mutes |
| | 3.1 Alert Channel Abstraction | P1 | Extensible polymorphic messaging system (webhooks, email, Slack) |
| | 3.3 Alert Acknowledgement Flow | P2 | Explicit dashboard ACK tracking with visual unread counts |
| **Track 4: Dashboard & UX** | 4.8 Client-Side API Caching & Debouncing | P1 | API data layer cache (SWR/React Query) preventing parallel load spikes |
| | 4.2 Event Detail View & Timeline | P1 | Graphical timeline showing clustering records and score history |
| | 4.3 Source Health Dashboard | P1 | Real-time source status, failure trends, and manual toggle buttons |
| | 4.1 Real-Time SSE/WebSocket Updates | P1 | Active event pushes directly streaming active alerts to dashboard |
| | 4.4 Scoring Explanation Panel | P2 | Graphical factor breakdowns showing cost penalties & bonuses |
| | 4.5 Auto-Refresh with Polling | P2 | Configurable background refresh slider in page headers |
| | 4.6 Mobile-Responsive Layout | P2 | Flex layouts, collapse systems, and cards for small-screen users |
| | 4.7 Dark/Light Theme Customizer | P3 | Systems color-matching sync settings for UI themes |
| **Track 5: Observability & Operations** | 5.4 Stale Command Reaper | P1 | Lock timing reap routines for aborted worker command scripts |
| | 5.5 Graceful Worker Shutdown | P1 | Signal handling interrupts (`SIGTERM`/`SIGINT`) for database loops |
| | 5.1 Structured Logging | P1 | Standardized JSON output log metrics for pipeline and LLM tracing |
| | 5.2 Pipeline Metrics & Performance Tracking | P1 | Processing timing trends persisted in `JobRun` history schemas |
| | 5.3 LLM Cost Tracking Dashboard | P1 | Active fee graphs showing token usage divided by analyzer tasks |
| | 5.6 Operational Alerts (Self-Monitoring) | P2 | Heartbeat and API state watchdog alarms fired to Telegram |
| | 5.7 Log Rotator Double Formatting Fix | P3 | Single-format log write enhancements inside custom log classes |
| **Track 6: Data Quality & Scale** | 6.1 Database-Level Deduplication | P1 | Hash constraints and index anti-joins instead of in-memory maps |
| | 6.7 Database Retention Integrity Fix | P1 | Cascade migrations or child-first deletes preventing FK sweep crashes |
| | 6.4 Event Merge/Split Operations | P2 | UI and API commands to manually decouple or group cluster lists |
| | 6.2 Source Quality Auto-Scoring | P2 | Multi-signal rating calculation dynamically tuning source scores |
| | 6.3 Incremental RSS Polling | P2 | ETag and Last-Modified network traffic optimization sweeps |
| | 6.5 Archived Event Compaction | P3 | Clean summary serialization drops old embedding matrices safely |
| | 6.6 Configurable Embedding Dimensions | P3 | Dimension settings loading to dynamically target modern embed types |
| **Track 7: Architecture, Quality & Testing** | 7.1 API Transaction Middleware & Safety | P0 | Consistent request transaction wrapping and session managers |
| | 7.2 Codebase Decoupling | P1 | Shared/API-owned command contracts instead of worker imports |
| | 7.3 Real-Database Integration Testing Stack | P1 | Multi-service testing profiles using real PG containers |
| | 7.4 Dashboard End-to-End (E2E) Test Suite | P2 | Playwright/Cypress automation of target user dashboard interactions |
