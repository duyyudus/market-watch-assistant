# React Dashboard Overview

**Last Updated:** June 14, 2026  
**Latest Commit:** `808545f9080fe9d4fce526e2730aa1366c98e668`

---

## 1. Introduction
The **Dashboard** ([dashboard](../dashboard)) is the front-end user interface built using **React 19**, **Vite**, **TypeScript**, and **Tailwind CSS** with **daisyUI** components. It enables real-time monitoring of market signals, event scoring histories, manual task execution, and pipeline configuration edits.

---

## 2. API Integration & Authentication (`src/api.ts`)
The client interacts with the FastAPI backend through the API wrapper in [api.ts](../dashboard/src/api.ts):

- **Base URL Discovery**: Derived from `import.meta.env.VITE_API_BASE_URL` or falls back to the current origin host at port `8000`.
- **Bearer Token Authentication**: Safe writes are enabled by appending the `Authorization: Bearer <Token>` header using the token configured via `VITE_API_AUTH_TOKEN`.
- **API Methods**: Contains direct function calls for fetching news feeds, modifying settings, acknowledging alerts, triggering commands, and previewing scrapers.

---

## 3. State Management & Polling (`src/app/useDashboardData.ts`)
Due to the decoupled nature of the backend worker processes, the dashboard uses a hook-based polling pattern in [useDashboardData.ts](../dashboard/src/app/useDashboardData.ts):

- **Bot Status & Queue Polling**: Periodic schedules retrieve running worker logs, active background job runs, and command execution queues.
- **Live Event Stream (SSE)**: In addition to polling, the hook opens an `EventSource` against the API's `/events/stream` endpoint (`eventStreamUrl()` in `api.ts`) to receive real-time event-cluster updates and heartbeats.
- **Local Cache & Updates**: Triggers UI updates when commands complete, automatically refreshing affected views (such as updating events lists after a recluster finishes).

---

## 4. Dashboard Feature Modules
The client source is organized into feature folders under [src/features/](../dashboard/src/features):

### Overview (`overview/`)
Displays aggregate statistics (e.g. news sources count, active alerts, coverage stats) and visualizes pipeline run status logs.

### Events (`events/`)
An interactive event explorer displaying:
- **Events Timeline**: Lists active event clusters with scores, headline titles, and regions.
- **News Item Adjacency**: Lists matching news articles linked to the cluster, highlighting lexical or semantic similarity scores.
- **Score History**: Visual breakdown of event metrics over time.
- **Move Correlations**: Associated market price moves.
- **Investigation Panel**: Displays Brave Search evidence and LLM synthesis reports.

### News (`news/`)
A structured grid of normalized news items. Users can click on items to view raw HTML, full-text extraction statuses, and entity relationships.

### Alerts (`alerts/`)
Lists alert decisions with acknowledge/dismiss actions, and administers alert channels (e.g. Telegram links) and suppression rules.

### Watchlist (`watchlist/`)
Allows users to add, edit, or disable asset symbols, aliases, regions, and tier levels (S, A, B, C, D) which feed the scoring engine.

### Sources (`sources/`)
Tooling for RSS/scraper administration:
- **Sources Table**: Enables toggling, score adjustments, and polling intervals.
- **Health Indicators**: Tracks latencies, daily item volumes, and consecutive errors.
- **Preview Tool**: Allows inputting URLs to preview feed parsing and full-text extractions in real-time.

### Operations & Control (`operations/` / `commands/`)
An operational console for manually launching worker tasks (e.g., executing a full pipeline, running missed catalyst reviews, or reclustering historical news).

### Maintenance (`maintenance/`)
Surfaces pipeline run metrics, LLM token usage and estimated costs, embedding coverage audits, and data-retention logs pulled from the `/maintenance` router.
