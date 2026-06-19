# React Dashboard Overview

**Last Updated:** June 19, 2026  
**Latest Commit:** `24f74c0fa88230d741f8b0397cb4056776c4614d`

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
The landing dashboard: system health and worker heartbeat liveness, the latest daily digest, and **per-segment spotlight event ranking**. Top events are fetched server-side per market segment — `global`, `us`, `vietnam`, and `crypto` (`EventSegment` in `api.ts`, loaded by `loadOverviewSegments`) — each with its own display limit.

### Events (`events/`)
An interactive event explorer (paginated, filterable, and sortable) displaying:
- **Events Timeline**: Lists active event clusters with scores, headline titles, and regions.
- **News Item Adjacency**: Lists matching news articles linked to the cluster, highlighting lexical or semantic similarity scores.
- **Score History**: Visual breakdown of event metrics over time.
- **Move Correlations**: Associated market price moves.
- **Investigation Panel**: Displays Brave Search evidence and LLM synthesis reports.

### News (`news/`)
A structured grid of normalized news items. Users can click on items to view raw HTML, full-text extraction statuses, and entity relationships.

### Alerts (`alerts/`)
A tabbed view (`AlertTabs`):
- **Decisions tab**: Paginated/filterable list of alert decisions with acknowledge/dismiss actions and a detail panel.
- **Settings tab**: Houses the alert policy, alert channels (e.g. Telegram links), and suppression rules (`tabs/settings/` — `AlertPolicyPanel`, `AlertChannelsPanel`, `AlertSuppressionRulesPanel`), migrated here from the former settings/maintenance surface.

### Watchlist (`watchlist/`)
Allows users to add, edit, or disable asset symbols, aliases, regions, and tier levels (S, A, B, C, D) which feed the scoring engine.

### Sources (`sources/`)
Tooling for RSS/scraper administration:
- **Sources Table**: Enables toggling, score adjustments, and polling intervals.
- **Health Indicators**: Tracks latencies, daily item volumes, and consecutive errors.
- **Preview Tool**: Allows inputting URLs to preview feed parsing and full-text extractions in real-time.

### Commands (`commands/`)
A manual command console for launching worker tasks (e.g. executing a full pipeline, running missed catalyst reviews, or reclustering historical news) via `CommandsTable`, plus a `CommandHistoryTable` for past runs.

### Maintenance (`maintenance/`)
Consolidated operational view (`MaintenanceTabs`) that absorbed the former standalone operations panel. Tabs cover pipeline metrics, fetch logs, job history, score history, embedding coverage, LLM runs and costs, missed-catalyst review, and retention audits — pulled largely from the `/maintenance` router.
