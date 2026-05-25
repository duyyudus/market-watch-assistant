# Market Watch Bot

Standalone MVP worker for personal market monitoring. The bot owns the first
database migrations, exposes the `market-watch` CLI, ingests RSS sources, stores
raw and normalized news items, clusters events, records alert decisions, and
builds log-only digests.

## Quick start

```bash
uv run market-watch init
uv run market-watch doctor
uv run market-watch migrate
uv run market-watch source list
uv run market-watch pipeline run --dry-run
```

Live database checks use `DATABASE_URL` from `.env`.
