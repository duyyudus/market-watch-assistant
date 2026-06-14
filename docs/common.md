# Database & Shared Common Layer Overview

**Last Updated:** June 14, 2026  
**Latest Commit:** `808545f9080fe9d4fce526e2730aa1366c98e668`

---

## 1. Introduction
The **Common Layer** ([common](../market-watch-bot/common)) houses the shared codebase used by both the FastAPI `api_server` and the background `bot_worker`. It contains the database models, database session managers, application configuration loaders, logging setups, external API clients, text normalization scripts, and symbol resolution libraries.

---

## 2. Database Models & Schema (`common/db/models.py`)
All persistent objects share a single Declarative Base inside [models.py](../market-watch-bot/common/db/models.py).

- **SQLAlchemy 2.0 Mapping**: Uses standard modern typing `Mapped[...]` and `mapped_column()`.
- **JSONB Dialect Support**: Utilizes Postgres `JSONB` format for unstructured payloads (such as raw feeds, quality metrics, and score breakdowns) while compiling to standard `JSON` when running unit tests with SQLite.
- **Custom Vector Type**: Implements the `Vector` user-defined type inheriting from `UserDefinedType` to support pgvector's `vector(1536)` type constraints, handling binding and result parsing.

Session initialization and session factory setups are handled via async SQLAlchemy configurations inside [session.py](../market-watch-bot/common/db/session.py).

---

## 3. Application Configuration (`common/config.py`)
The configuration loader ([config.py](../market-watch-bot/common/config.py)) dynamically builds configuration sets:

1. **`settings.yml`**: Contains non-secret presets — clustering/scoring thresholds, model details (embeddings `openai/text-embedding-3-large` at 1536 dims; LLM `google/gemini-3.1-flash-lite`), retry/cooldown policies, market-data providers, and investigation domain lists.
2. **`.env` (Environment variables)**: Supplies secrets referenced by `*_env` keys — `DATABASE_URL`, `OPENROUTER_API_KEY`, `BRAVE_SEARCH_API_KEY`, Telegram credentials, and `API_AUTH_TOKEN`.

---

## 4. LLM Client Wrapper (`common/llm.py`)
The unified AI access layer is implemented in [llm.py](../market-watch-bot/common/llm.py):

- **LLM Prompt Templates**: Stores prompts for entity extraction, ambiguous clustering, event enrichment/scoring, and agentic investigations, with prompt versions/hashes recorded for cache reuse via `LLMAnalysisRun`.
- **OpenRouter Chat Provider**: `OpenRouterChatProvider` posts to the OpenAI-compatible `/chat/completions` endpoint, with structured-output (schema) validation, concurrency limits, and shared retry/cooldown policies.
- **Token Auditing**: Tallies prompt/completion tokens, mapping usages to cost models to display live estimated spend breakdowns on the dashboard.

---

## 5. Normalization, Parsing, & Resolvers
Shared utilities handle data scrubbing and integrations:

- **HTML Normalization (`normalize.py` / `crawler.py` / `rss.py`)**: Scrubs HTML tags, removes tracking parameters from links, detects boilerplate text patterns, and parses XML feeds.
- **Symbol Resolution (`market_symbol_resolver.py`)**: Translates LLM-extracted names or aliases into index codes or trading tickers across the configured providers (Hyperliquid for global, CoinGecko/Binance for crypto, the VN market service for Vietnam), caching outcomes in `MarketSymbolResolution`.
