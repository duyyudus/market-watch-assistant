# Market Watch Assistant 1.0 Roadmap Progress

Updated: 2026-06-01

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

## Track 2: Pipeline Intelligence

Status: Completed

### 2.1 Retry & Backoff for External APIs

- Added shared provider retry/backoff helpers with provider-specific retry policies for RSS, market APIs, OpenRouter chat/embeddings, Telegram, and Brave Search.
- Added `429` handling with `Retry-After` support and cooldown recording hooks.
- Wired retry handling into RSS fetches, OpenRouter embeddings, OpenRouter chat completions, Brave Search, and Telegram sends.

### 2.2 Per-Provider Rate Limiting & 429 Cooldowns

- Added `provider_cooldowns` persistence in Alembic revision `0009_pipeline_intelligence.py`.
- Added provider cooldown helper APIs and pipeline stats for rate-limit skips and provider degradation.

### 2.3 Actual Watchlist Tier-Based Scoring

- Added watchlist-tier resolution for matched entities/tickers and propagated actual S/A/B/C/D tiers through event clustering, rescore, alert decisions, bot commands, and LLM scoring inputs.
- Kept the previous A-tier fallback only for test/fake-session paths where no watchlist rows are available.

### 2.4 Digest Generation & Delivery

- Added persisted `digests` records with window, content, event count, delivery status, channel, recipient, response, error, and sent timestamp.
- Added daily digest formatting grouped by region/asset class.
- Added digest build/send service helpers, `digest.send` bot command support, and worker daily digest scheduling at 8 AM configured bot timezone.

### 2.5 Multi-Source Confirmation Boosting

- Added `unique_high_quality_source_count` to `ScoreInput`.
- Added high-quality source counting for event drafts/clusters and confidence boosting for diverse high-quality coverage.

### 2.6 Smart Polling Intervals

- Added source polling state fields: `last_fetched_at`, `consecutive_failure_count`, `burst_until_at`, and `disabled_until_at`.
- Added interval-aware source skipping, 30-minute burst mode after newly inserted RSS items, and failure cooldown after 3 consecutive failures.
- Surfaced skipped and failed source counts in pipeline results.

### 2.7 Web Crawler / Full-Text Extraction

- Added `trafilatura` to backend dependencies.
- Added full-text extraction for high-priority/single-source events with graceful failure isolation.
- Added `NormalizedNewsItem.raw_content` persistence and LLM prompt inclusion when full text is available.

### 2.8 Embedding-Based Cross-Language Clustering

- Added Vietnamese-aware entity extraction prompt guidance and language/raw-content metadata in LLM snapshots.
- Preserved embedding-based cluster attachment flow for multilingual items while improving source-language context for entity extraction.

### 2.9 Robust Market Data Fetch Error Handling

- Added `fetch_market_moves_with_stats()` with provider-level degraded/failed reporting.
- Hardened Binance-to-CoinGecko fallback to catch HTTP, JSON, parser, and unexpected response errors per symbol without aborting the whole fetch.

### 2.10 Pipeline Degradation Reporting

- Added `degraded_stages`, `failed_stages`, `rate_limit_skips`, and `provider_retries` fields to pipeline results.
- Marked provider throttling, source polling skips/failures, embedding/LLM failures, market fetch degradation, investigation failures, full-text extraction failures, alert dispatch failures, and missed-catalyst review failures.

### 2.11 Type-Safe Vector SQL Parameterized Casting

- Added Python vector validation before pgvector queries.
- Refactored vector search to bind the query vector through the shared `Vector` SQLAlchemy type instead of passing a raw serialized literal.
- Removed `pgvector_literal` from the public `bot_worker.services` export surface.

### 2.12 Dead Exports Cleanup

- Removed nonexistent `run_move_investigation` from `bot_worker.services.__all__`.

## Track 3: Alert & Delivery

Status: Completed

### 3.1 Alert Channel Abstraction

- Added persisted `alert_channels` records with channel type, configuration, enabled state, default flag, and timestamps.
- Added channel-aware delivery support for log, Telegram, and generic webhook JSON alerts.
- Added Telegram text and webhook JSON formatting paths.
- Added dashboard channel management and channel test actions that enqueue worker commands through `bot_commands`.

### 3.2 Alert Suppression Rules

- Added persisted `alert_suppression_rules` records with rule type, configuration, enabled state, and timestamps.
- Added cooldown, quiet-hours, region/category filter, and entity/ticker mute evaluation before immediate delivery.
- Added dashboard suppression rule management for the supported rule types.

### 3.3 Alert Acknowledgement Flow

- Added `acknowledged_at` to alert decisions.
- Added API endpoints to acknowledge and dismiss alerts.
- Added dashboard unacknowledged alert badge plus acknowledge/dismiss controls in the alerts view.

### 3.4 Failed Alert Retry Queue

- Added delivery retry metadata: `attempt_count`, `next_attempt_at`, and `permanently_failed_at`.
- Updated alert dispatch to retry failed delivery records after the retry window.
- Added max-attempt handling that marks exhausted deliveries as `permanently_failed`.

## Track 4: Dashboard Live UX

Status: Completed

### Live Event Updates

- Added `GET /events/stream` as a read-only `text/event-stream` endpoint.
- Added heartbeat messages plus database-polled `alert.created`, `pipeline.completed`, and `command.updated` events from shared tables.
- Kept the stream decoupled from worker execution; it reads persisted records only.

### Event Details

- Extended `GET /events/{event_id}` with timeline items, score history, latest alert, latest investigation, relevant LLM runs, and related market moves.
- Added typed API response models for the richer event detail payload.
- Reworked the dashboard event detail area into timeline, LLM analysis, investigation, market moves, scoring, and action sections.
- Added score component bars and penalty indicators using CSS only.

### Source Health

- Added `GET /sources/health`.
- Returned latest fetch status, last fetch time, failure streak, average latency, 7-day item counts, and computed `healthy`, `degraded`, or `failing` state.
- Added the dashboard source health sub-tab with status indicators, item-count spark bars, test fetch, enable/disable, and edit controls.

### Dashboard Data Loading

- Added a small client resource cache with TTL, in-flight request deduplication, explicit invalidation, and debounced reload helpers.
- Replaced eager loading with view-aware resource loading: overview loads status/events/alerts, and each view loads only its own resources plus shared status as needed.
- Added an SSE client subscription that invalidates and refreshes only affected resources for alert, pipeline, and command messages.
- Added persisted auto-refresh fallback options: off, 30s, 60s, and 5m.

### Responsive UI & Theme

- Added responsive card views for events, alerts, and sources while preserving desktop tables.
- Added persisted theme selection for `system`, `dark`, and `light`.
- Added a light daisyUI theme and system-mode handling through `prefers-color-scheme`.

## Track 5: Observability & Operations

Status: Completed

### Structured Logging

- Added JSON log formatting for backend console and file handlers with timestamp, level, logger, message, and contextual fields.
- Preserved Telegram token redaction in structured log messages and contextual payloads.
- Fixed line-based log rotation so each record is formatted once and that formatted value is reused for line counting.

### Pipeline Metrics

- Added pipeline run and stage metrics with timing, throughput, and stage status.
- Persisted metrics in `JobRun.result["pipeline_metrics"]`.
- Added slow-stage detection against recent successful pipeline run averages using the configured 2x threshold.

### Worker Operations

- Added stale running-command reaping with a 10-minute default timeout and timeout failure reason.
- Added graceful worker shutdown handling for `SIGTERM` and `SIGINT`.
- Added operational self-monitoring alerts for stale pipeline heartbeat, broad source failures, and repeated LLM failures with one-hour duplicate suppression.

### Maintenance Dashboard

- Added API endpoints for LLM token/cost summaries and pipeline metrics.
- Added Maintenance dashboard tabs for LLM cost tracking and pipeline performance metrics.
- Kept LLM cost estimation conservative: known models use built-in pricing defaults, and unknown models report token usage with zero estimated cost.

## Track 6: Data Quality & Scale

Status: Completed

### Database-Level Deduplication

- Added Alembic revision `0011_data_quality_scale.py` with a partial active normalized-news dedup index on `(canonical_url_hash, title_hash)`.
- Replaced in-memory duplicate detection with a database window-update flow that marks later normalized rows as `deduped`.
- Updated normalization to use the effective source score for newly normalized items.

### Source Quality Auto-Scoring

- Added persisted source quality fields: `auto_quality_score`, `quality_metrics`, and `quality_calculated_at`.
- Added quality scoring based on 30-day reliability (50% weight), duplicate rate (20% weight), and event contribution (30% weight), simplified to ensure complete immunity to worker downtime and network-induced freshness delays.
- Added `market-watch source quality refresh` and `source.quality.refresh` worker command support.

### Incremental RSS Polling

- Added `etag` and `last_modified` source metadata.
- RSS fetches now send conditional headers and handle `304 Not Modified` without parsing or inserting raw items.
- Successful `200` fetches persist returned `ETag` and `Last-Modified` headers.

### Event Merge/Split Operations

- Reworked event merge to move cluster item links, delete stale embeddings, rescore the target cluster, and mark the source cluster as `merged`.
- Added event split support that moves selected news items into a new event cluster and rescores both clusters.
- Added CLI commands, worker command types, API command validation, and dashboard command-center controls for merge and split.

### Archived Event Compaction

- Added `archive_summary` and `compacted_at` fields on event clusters.
- Added archived-event compaction service, CLI command, worker command, and dashboard controls.
- Compaction preserves cluster rows, item links, alert decisions, and score history while removing old event/news embeddings.

### Embedding Dimension Validation

- Added explicit validation that non-local embedding configurations match the current `vector(1536)` database columns.
- Kept local embedding tests flexible for small-dimension unit vectors while preventing incompatible persisted vectors.

### Retention Integrity

- Updated retention sweeps to delete dependent rows before parent rows for alerts, event clusters, normalized news items, embeddings, entities, and related reviews.
- Added model/migration `ON DELETE` metadata where appropriate while keeping service-level deletion order portable across SQLite and Postgres.

### Dashboard/API Surface

- Extended source API responses and dashboard source types with optional quality score fields.
- Dashboard queues all new operational actions through `bot_commands`; it does not call worker services directly.

## Verification

- `cd market-watch-bot && UV_CACHE_DIR=/tmp/uv-cache uv run pytest --ignore=tests/test_api_contract.py -q` -> 212 passed.
- `cd market-watch-bot && UV_CACHE_DIR=/tmp/uv-cache DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest tests/test_api_contract.py -q` -> 20 passed.
- `cd market-watch-bot && uv run pytest tests/test_migration_0010.py tests/test_normalization.py tests/test_pipeline_intelligence.py tests/test_events.py tests/test_retention.py tests/test_embeddings.py tests/test_bot_commands.py -q` -> 57 passed.
- `cd market-watch-bot && uv run ruff check .` -> all checks passed.
- `cd dashboard && npm test -- --run` -> 39 passed.
- `cd dashboard && npm run lint` -> TypeScript check passed.
- `cd dashboard && npm run build` -> build completed.

## Operational Notes

- `docker-compose.yml` mounts `market-watch-bot/.env` into backend containers instead of using Compose `env_file`, so `docker compose config` does not expand local secrets into rendered service environment output.
- Sandboxed `aiosqlite.connect(":memory:")` timed out in this Codex environment, but the same API contract suite passed outside the sandbox. The timeout was isolated to sandboxed async SQLite startup rather than API endpoint behavior.
- No live containers, live migrations, live market-data calls, OpenRouter calls, Brave calls, Telegram sends, webhook posts, or live pipeline commands were run for Track 3 or dashboard verification.
- A sandboxed full `DATABASE_URL=sqlite+aiosqlite:///:memory: uv run pytest -q` attempt did not complete after the first 16 tests in this session; the focused API contract suite, dashboard tests, dashboard build, ruff, and rendered Playwright validation completed successfully.
