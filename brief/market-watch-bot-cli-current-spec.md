# `market-watch-bot` Current CLI Specification

Date: 2026-05-28

This document is the current recommended CLI surface for the implemented
`market-watch-bot`. It intentionally does not replace
`market-watch-bot-cli-manual.md`, which remains a broader historical/reference
manual.

The current CLI should prioritize operator debugging, database-backed inspection,
and explicit maintenance actions. It should avoid speculative daemon controls,
duplicate namespaces, and infrastructure commands that are better handled outside
the bot.

---

## Recommended CLI Tree

```txt
market-watch
  init
  migrate
  doctor

  worker
    start
    status
    logs
    health

  source
    add
    list
    show
    enable
    disable
    purge
    test
    fetch
    import
    export

  job
    list
    run
    history
    failures

  pipeline
    run
    inspect
    stats

  news
    list
    show
    search
    entities

  event
    list
    show
    merge
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
    channel
      show
    test
    list
    show
    send-test
    dispatch

  digest
    build
    preview

  embedding
    status
    backfill
    search

  llm
    classify
    enrich
    summarize
    score
    test
    usage

  investigate
    event
    asset
    move
    pending
    run-pending
    show

  market
    fetch
    move
    movers
    join

  catalyst
    review
    list
    show
    resolve

  retention
    show
    preview
    run
    reset-baseline

  health
    sources
    jobs
    db
    alerts
    pipeline

  server
    start
```

---

## High-Value Operator Commands

These are the commands expected to matter most during daily operation and
debugging:

```bash
market-watch source test <source>
market-watch pipeline inspect --item <news_id>
market-watch news show <news_id>
market-watch event show <event_id>
market-watch alert test --event <event_id>
market-watch watchlist match "<headline>"
market-watch health pipeline
market-watch health alerts
market-watch catalyst review --window 1d
```

---

## `job run` Scope

Keep `market-watch job run`, but only for direct full-job runners:

```bash
market-watch job run pipeline
market-watch job run retention_cleanup
```

Registered pipeline stages such as `poll_sources`, `normalize_raw_items`, and
`cluster_events` are not standalone CLI jobs. If requested through `job run`, the
CLI should fail clearly and direct the operator to `pipeline run` or
`worker start`.

This keeps `job run` useful for manual operations without pretending the bot has
a full scheduler/admin layer.

---

## Intentionally Out Of Scope

The following commands are intentionally excluded from the current recommended
CLI:

```txt
worker stop/restart
config show/set
job show/enable/disable/schedule/retry
pipeline replay
event search/similar/split
alert policy set/reset
alert suppress/unsuppress
digest send/history
vector namespace
review namespace
market source registry
retention set/vacuum
root import/export/backup commands
```

Use shell signals, Docker, systemd, or another process manager for worker
lifecycle. Use `settings.yml` for persistent policy/config edits. Use database
infrastructure tools for backup and restore.
