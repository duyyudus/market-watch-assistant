Below is a practical CLI command set for a **standalone market-watch-bot**.

Assume binary name:

```bash
market-watch
```

Recommended structure:

```txt
market-watch <domain> <action> [options]
```

---

# 1. Worker lifecycle commands

These manage the actual background worker.

```bash
market-watch worker start
market-watch worker stop
market-watch worker restart
market-watch worker status
market-watch worker logs
market-watch worker health
```

## Essential examples

```bash
market-watch worker start
```

Starts all enabled jobs according to schedule.

```bash
market-watch worker start --only poll_sources,normalize,dedupe
```

Starts only selected jobs.

```bash
market-watch worker health
```

Checks:

```txt
database connection
pgvector availability
source count
enabled jobs
last successful fetch
queue depth
failed job count
alert dispatcher status
```

```bash
market-watch worker logs --tail 200
```

Shows recent worker logs.

---

# 2. Initial setup commands

These are needed for first-time setup.

```bash
market-watch init
market-watch migrate
market-watch config show
market-watch config set
market-watch doctor
```

## Examples

```bash
market-watch init
```

Creates default config file, default source categories, default retention policy, and default alert thresholds.

```bash
market-watch migrate
```

Runs database migrations.

```bash
market-watch doctor
```

Checks environment:

```txt
DATABASE_URL exists
database reachable
pgvector installed
required tables exist
embedding provider configured
LLM provider configured
alert channel configured
timezone configured
```

```bash
market-watch config show
```

Shows current worker config.

```bash
market-watch config set timezone Asia/Ho_Chi_Minh
market-watch config set default_language en
market-watch config set embedding.provider openai
```

---

# 3. Source management commands

These are essential because sources are the foundation of the bot.

```bash
market-watch source add
market-watch source list
market-watch source show
market-watch source update
market-watch source enable
market-watch source disable
market-watch source remove
market-watch source test
market-watch source fetch
market-watch source import
market-watch source export
```

## Add RSS source

```bash
market-watch source add rss \
  --name "Investing.com Breaking News" \
  --url "https://www.investing.com/rss/news.rss" \
  --region global \
  --category global_macro \
  --language en \
  --score 70 \
  --interval 300
```

## Add official source

```bash
market-watch source add rss \
  --name "Federal Reserve Press Releases" \
  --url "https://www.federalreserve.gov/feeds/press_all.xml" \
  --region us \
  --category global_macro \
  --type official \
  --language en \
  --score 100 \
  --interval 300
```

## Add Google News RSS source

```bash
market-watch source add google-news \
  --name "Google News - Fed Rate Cut" \
  --query "Fed rate cut" \
  --region us \
  --language en \
  --category global_macro \
  --score 60 \
  --interval 900
```

## Add Vietnam source

```bash
market-watch source add rss \
  --name "Vietstock" \
  --url "https://vietstock.vn/rss.htm" \
  --region vietnam \
  --category vietnam_equity \
  --language vi \
  --score 70 \
  --interval 600
```

## Test a source

```bash
market-watch source test vietstock
```

Should show:

```txt
status: success
items found: 20
latest item time: 2026-05-24 09:30:00 +07
parser: rss
sample title: ...
```

## Fetch one source manually

```bash
market-watch source fetch vietstock
```

Useful for debugging without starting full worker.

## List sources

```bash
market-watch source list
market-watch source list --enabled
market-watch source list --region vietnam
market-watch source list --category crypto
market-watch source list --type official
```

## Export/import source config

```bash
market-watch source export --out sources.yaml
market-watch source import sources.yaml
```

This is important because you will probably tune source lists manually.

---

# 4. Job management commands

The worker should expose jobs explicitly.

```bash
market-watch job list
market-watch job show
market-watch job enable
market-watch job disable
market-watch job run
market-watch job schedule
market-watch job history
market-watch job retry
market-watch job failures
```

## Core jobs

Recommended built-in jobs:

```txt
poll_sources
normalize_raw_items
dedupe_news_items
extract_entities
generate_embeddings
cluster_events
join_market_data
score_events
dispatch_alerts
build_digest
missed_catalyst_review
retention_cleanup
source_health_check
```

## Examples

```bash
market-watch job list
```

Shows all jobs and schedules.

```bash
market-watch job run poll_sources
```

Runs source polling once.

```bash
market-watch job run normalize_raw_items --limit 500
```

Normalizes up to 500 raw items.

```bash
market-watch job run cluster_events --since "24h"
```

Re-clusters recent items.

```bash
market-watch job run retention_cleanup
```

Runs retention deletion/archive.

```bash
market-watch job failures --since "7d"
```

Shows failed jobs.

```bash
market-watch job retry --failed --since "24h"
```

Retries failed job executions.

---

# 5. Pipeline commands

These are useful for running or debugging individual pipeline stages.

```bash
market-watch pipeline run
market-watch pipeline replay
market-watch pipeline inspect
market-watch pipeline stats
```

## Run full pipeline once

```bash
market-watch pipeline run
```

Equivalent to:

```txt
poll → normalize → dedupe → entities → embeddings → cluster → score → alert
```

## Run pipeline for one source

```bash
market-watch pipeline run --source vietstock
```

## Run without sending alerts

```bash
market-watch pipeline run --dry-run
```

Very important for testing.

## Replay raw data

```bash
market-watch pipeline replay --since "7d"
```

Useful when parser/classifier logic changes.

## Inspect one item through pipeline

```bash
market-watch pipeline inspect --item news_123
```

Should show:

```txt
raw item
normalized item
dedupe result
entities
embedding status
cluster decision
score breakdown
alert decision
```

This command is extremely useful.

---

# 6. News item commands

These help inspect ingested data.

```bash
market-watch news list
market-watch news show
market-watch news search
market-watch news dedupe
market-watch news entities
market-watch news similar
```

## Examples

```bash
market-watch news list --since "1h"
market-watch news list --source vietstock --since "24h"
market-watch news list --region crypto --limit 50
```

```bash
market-watch news show news_123
```

Shows normalized fields, source, snippet, URL, entities, cluster, score.

```bash
market-watch news search "China property stimulus"
```

Searches title/snippet/full-text metadata.

```bash
market-watch news similar news_123
```

Uses embeddings to show similar items.

```bash
market-watch news entities news_123
```

Displays extracted entities and confidence.

---

# 7. Event cluster commands

Event clusters are the most important object.

```bash
market-watch event list
market-watch event show
market-watch event search
market-watch event similar
market-watch event merge
market-watch event split
market-watch event rescore
market-watch event recluster
market-watch event mark
```

## List recent events

```bash
market-watch event list --since "24h"
market-watch event list --region vietnam
market-watch event list --asset-class crypto
market-watch event list --min-score 70
market-watch event list --status reported
```

## Show event

```bash
market-watch event show evt_123
```

Should display:

```txt
canonical headline
summary
status
first seen
last updated
source count
source list
affected assets
affected tickers
score breakdown
alert history
related news items
```

## Search events

```bash
market-watch event search "Hormuz oil shipping"
market-watch event search "FTSE Vietnam upgrade"
market-watch event search "Binance listing"
```

## Find similar historical events

```bash
market-watch event similar evt_123
```

Useful for recurring topics.

## Merge duplicate clusters

```bash
market-watch event merge evt_123 evt_456
```

## Split wrongly clustered item

```bash
market-watch event split evt_123 --item news_789
```

## Rescore event

```bash
market-watch event rescore evt_123
```

## Recluster recent items

```bash
market-watch event recluster --since "48h"
```

## Mark status manually

```bash
market-watch event mark evt_123 --status official
market-watch event mark evt_123 --status stale
market-watch event mark evt_123 --status false_signal
```

Manual override is useful for personal systems.

---

# 8. Watchlist commands

The alert policy depends heavily on watchlists.

```bash
market-watch watchlist add
market-watch watchlist list
market-watch watchlist show
market-watch watchlist update
market-watch watchlist remove
market-watch watchlist import
market-watch watchlist export
market-watch watchlist match
```

## Add watched stock

```bash
market-watch watchlist add \
  --symbol VIC \
  --name "Vingroup" \
  --type stock \
  --region vietnam \
  --asset-class equity \
  --tier A \
  --alias "Vingroup" \
  --alias "VinGroup"
```

## Add crypto token

```bash
market-watch watchlist add \
  --symbol BTC \
  --name "Bitcoin" \
  --type crypto \
  --asset-class crypto \
  --tier A \
  --alias "Bitcoin"
```

## Add macro theme

```bash
market-watch watchlist add \
  --name "Strait of Hormuz" \
  --type macro_theme \
  --asset-class commodity \
  --tier A \
  --alias "Hormuz" \
  --alias "Persian Gulf shipping"
```

## List watchlist

```bash
market-watch watchlist list
market-watch watchlist list --tier A
market-watch watchlist list --region vietnam
```

## Test matching

```bash
market-watch watchlist match "Oil jumps after tanker incident near Hormuz"
```

Should return:

```txt
Matched:
- Strait of Hormuz, tier A, macro_theme
- Oil, commodity
```

This is very important for debugging relevance scoring.

---

# 9. Alert policy commands

You need CLI control over thresholds, cooldowns, and suppression.

```bash
market-watch alert policy show
market-watch alert policy set
market-watch alert policy reset
market-watch alert test
market-watch alert list
market-watch alert show
market-watch alert send-test
market-watch alert suppress
market-watch alert unsuppress
```

## Show policy

```bash
market-watch alert policy show
```

## Set thresholds

```bash
market-watch alert policy set immediate_threshold 80
market-watch alert policy set watchlist_threshold 55
market-watch alert policy set digest_threshold 30
```

## Set tier-specific threshold

```bash
market-watch alert policy set tier.A.immediate_threshold 70
market-watch alert policy set tier.B.immediate_threshold 80
market-watch alert policy set general.immediate_threshold 90
```

## Set cooldown

```bash
market-watch alert policy set cooldown.macro 21600
market-watch alert policy set cooldown.crypto 3600
```

Seconds are easier for config; display should show human-readable duration.

## Test alert decision

```bash
market-watch alert test --event evt_123
```

Shows:

```txt
final score
threshold matched
decision
cooldown status
suppression reason
would send? yes/no
```

## List alerts

```bash
market-watch alert list --since "24h"
market-watch alert list --level immediate
market-watch alert list --suppressed
```

## Send test alert

```bash
market-watch alert send-test --channel telegram
```

---

# 10. Digest commands

Digest generation should be manually runnable.

```bash
market-watch digest build
market-watch digest preview
market-watch digest send
market-watch digest history
```

## Examples

```bash
market-watch digest preview --period daily
market-watch digest preview --period daily --region vietnam
market-watch digest preview --period daily --asset-class crypto
```

```bash
market-watch digest send --period daily
```

```bash
market-watch digest build --from "2026-05-24 00:00" --to "2026-05-24 08:00"
```

Useful for customized morning/evening briefings.

---

# 11. Embedding/vector commands

Since pgvector is part of the design, expose operational commands.

```bash
market-watch vector status
market-watch vector embed
market-watch vector reembed
market-watch vector search
market-watch vector rebuild
market-watch vector stats
```

## Status

```bash
market-watch vector status
```

Shows:

```txt
pgvector installed: yes
embedding model
dimensions
news items embedded
event clusters embedded
pending embeddings
failed embeddings
```

## Embed pending items

```bash
market-watch vector embed --pending --limit 1000
```

## Re-embed event clusters

```bash
market-watch vector reembed events --since "30d"
```

## Search vector index

```bash
market-watch vector search "China property stimulus and iron ore impact"
```

## Rebuild index

```bash
market-watch vector rebuild --type events
```

Useful after model change.

---

# 12. LLM commands

Useful for debugging classification and summarization.

```bash
market-watch llm classify
market-watch llm summarize
market-watch llm score
market-watch llm test
market-watch llm usage
```

## Classify one news item

```bash
market-watch llm classify --item news_123
```

## Summarize one event

```bash
market-watch llm summarize --event evt_123
```

## Score one event

```bash
market-watch llm score --event evt_123
```

## Dry-run prompt

```bash
market-watch llm test --event evt_123 --show-prompt
```

Important for prompt debugging.

## Usage

```bash
market-watch llm usage --since "7d"
```

Shows estimated cost and token usage if tracked.

---

# 13. Agent investigation commands

The agent should be manually triggerable but constrained.

```bash
market-watch investigate event
market-watch investigate asset
market-watch investigate move
market-watch investigate pending
market-watch investigate show
```

## Investigate event

```bash
market-watch investigate event evt_123
```

Runs:

```txt
related source search
official source check
market data check
historical event comparison
recommended alert level
```

## Investigate asset move

```bash
market-watch investigate move \
  --symbol BTC \
  --window 4h
```

Useful for missed catalyst review.

## Investigate Vietnam stock

```bash
market-watch investigate asset \
  --symbol VIC \
  --since "24h"
```

## Show pending investigations

```bash
market-watch investigate pending
```

## Show result

```bash
market-watch investigate show inv_123
```

Agent should return to the policy engine, not send alert directly.

---

# 14. Market data commands

Even if the dashboard/API is separate, the worker needs market-data hooks for scoring.

```bash
market-watch market source add
market-watch market source list
market-watch market fetch
market-watch market move
market-watch market movers
market-watch market join
```

## Add market data source

```bash
market-watch market source add \
  --name "Binance Spot" \
  --type crypto \
  --provider binance
```

```bash
market-watch market source add \
  --name "VN Stock Data" \
  --type equity \
  --provider custom
```

## Fetch market data

```bash
market-watch market fetch --symbol BTCUSDT --window 1h
```

## Show movers

```bash
market-watch market movers --asset-class crypto --window 4h --min-change 3
market-watch market movers --region vietnam --window 1d --min-change 3
```

## Join events with market moves

```bash
market-watch market join --since "24h"
```

This updates event scores using price/volume reaction.

---

# 15. Missed-catalyst review commands

This is important enough to have its own CLI domain.

```bash
market-watch review missed
market-watch review list
market-watch review show
market-watch review resolve
```

## Run missed-catalyst review

```bash
market-watch review missed --window 1d
market-watch review missed --asset-class crypto --window 4h
market-watch review missed --region vietnam --window 1d
```

## List review items

```bash
market-watch review list --status pending
```

## Show review

```bash
market-watch review show review_123
```

## Resolve manually

```bash
market-watch review resolve review_123 --status no_clear_catalyst
market-watch review resolve review_123 --event evt_456
```

---

# 16. Retention commands

Needed for DB hygiene.

```bash
market-watch retention show
market-watch retention set
market-watch retention run
market-watch retention preview
market-watch retention vacuum
```

## Show policy

```bash
market-watch retention show
```

## Set retention

```bash
market-watch retention set raw_news_items 60d
market-watch retention set normalized_news_items 180d
market-watch retention set fetch_logs 14d
market-watch retention set event_clusters 1095d
market-watch retention set high_impact_alerts forever
```

## Preview deletion

```bash
market-watch retention preview
```

Shows how many rows would be deleted.

## Run cleanup

```bash
market-watch retention run
```

## Vacuum/analyze

```bash
market-watch retention vacuum
```

Useful after large cleanup jobs.

---

# 17. Source health and diagnostics commands

You will need this once source count grows.

```bash
market-watch health sources
market-watch health jobs
market-watch health db
market-watch health alerts
market-watch health pipeline
```

## Source health

```bash
market-watch health sources
```

Shows:

```txt
source
enabled
last fetch
last success
failure rate
items per day
latest item age
parser errors
```

## Stale sources

```bash
market-watch health sources --stale
```

Shows sources that have not produced data recently.

## DB health

```bash
market-watch health db
```

Checks table sizes, indexes, pgvector, migrations.

## Pipeline health

```bash
market-watch health pipeline
```

Shows queue/backlog:

```txt
raw pending normalization
normalized pending dedupe
items pending embeddings
items pending clustering
events pending scoring
alerts pending delivery
```

---

# 18. Import/export commands

Important for portability and reproducibility.

```bash
market-watch export sources
market-watch export watchlist
market-watch export config
market-watch export events
market-watch import sources
market-watch import watchlist
market-watch import config
```

## Examples

```bash
market-watch export sources --out sources.yaml
market-watch export watchlist --out watchlist.yaml
market-watch export config --out config.yaml
```

```bash
market-watch import sources sources.yaml
market-watch import watchlist watchlist.yaml
```

## Export event archive

```bash
market-watch export events \
  --since "2026-01-01" \
  --out events.jsonl
```

Useful for backtesting and future model tuning.

---

# 19. Backfill commands

Useful when adding a new source or changing logic.

```bash
market-watch backfill source
market-watch backfill embeddings
market-watch backfill entities
market-watch backfill clusters
market-watch backfill scores
```

## Examples

```bash
market-watch backfill source vietstock --since "30d"
```

Only possible if the source/API supports historical fetch.

```bash
market-watch backfill entities --since "180d"
market-watch backfill embeddings --since "180d"
market-watch backfill clusters --since "30d"
market-watch backfill scores --since "30d"
```

Backfill commands should support:

```bash
--dry-run
--limit
--batch-size
--resume
```

---

# 20. Backup/restore commands

Since this is standalone personal infrastructure:

```bash
market-watch backup create
market-watch backup list
market-watch backup restore
```

## Examples

```bash
market-watch backup create --out backup-2026-05-24.dump
market-watch backup list
market-watch backup restore backup-2026-05-24.dump
```

Optional, but useful.

---

# 21. Recommended minimum CLI for MVP

If you want to avoid overbuilding, start with these.

## Must-have MVP commands

```bash
market-watch init
market-watch migrate
market-watch doctor

market-watch source add
market-watch source list
market-watch source test
market-watch source fetch
market-watch source enable
market-watch source disable

market-watch worker start
market-watch worker status
market-watch worker logs

market-watch job list
market-watch job run
market-watch job history

market-watch pipeline run
market-watch pipeline inspect

market-watch news list
market-watch news show
market-watch news search

market-watch event list
market-watch event show
market-watch event merge
market-watch event rescore

market-watch watchlist add
market-watch watchlist list
market-watch watchlist match

market-watch alert policy show
market-watch alert policy set
market-watch alert test
market-watch alert list

market-watch digest preview
market-watch digest send

market-watch retention show
market-watch retention run

market-watch health sources
market-watch health pipeline
```

## Add after MVP

```bash
market-watch vector status
market-watch vector embed
market-watch vector search

market-watch investigate event
market-watch investigate move

market-watch review missed

market-watch backfill embeddings
market-watch backfill clusters

market-watch export sources
market-watch import sources
```

---

# 22. Suggested command hierarchy

Final recommended CLI tree:

```txt
market-watch
  init
  migrate
  doctor
  config

  worker
    start
    stop
    restart
    status
    logs
    health

  source
    add
    list
    show
    update
    enable
    disable
    remove
    test
    fetch
    import
    export

  job
    list
    show
    enable
    disable
    run
    schedule
    history
    retry
    failures

  pipeline
    run
    replay
    inspect
    stats

  news
    list
    show
    search
    similar
    entities

  event
    list
    show
    search
    similar
    merge
    split
    rescore
    recluster
    mark

  watchlist
    add
    list
    show
    update
    remove
    import
    export
    match

  alert
    policy
      show
      set
      reset
    test
    list
    show
    send-test
    suppress
    unsuppress

  digest
    build
    preview
    send
    history

  vector
    status
    embed
    reembed
    search
    rebuild
    stats

  llm
    classify
    summarize
    score
    test
    usage

  investigate
    event
    asset
    move
    pending
    show

  market
    source
      add
      list
    fetch
    move
    movers
    join

  review
    missed
    list
    show
    resolve

  retention
    show
    set
    preview
    run
    vacuum

  health
    sources
    jobs
    db
    alerts
    pipeline

  import
  export
  backup
```

---

# 23. Most important CLI commands in practice

The commands you will probably use most:

```bash
market-watch source test <source>
market-watch pipeline inspect --item <news_id>
market-watch event show <event_id>
market-watch alert test --event <event_id>
market-watch watchlist match "<headline>"
market-watch health pipeline
market-watch health sources
market-watch review missed --window 1d
```

These are the commands that make the system debuggable.

The CLI should not only control the worker. It should explain **why the bot behaved the way it did**.
