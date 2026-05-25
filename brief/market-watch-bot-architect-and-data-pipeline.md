# Implementation Brief: Market Watch Bot Mechanics & Data Pipeline

## 1. Scope

This brief covers the backend mechanics of a **personal-use market watch bot** that monitors:

```txt
Global markets
Vietnam market
Crypto markets
```

The focus is only on:

```txt
news ingestion
source management
normalization
deduplication
event clustering
market impact scoring
alert generation
retention
embedding/vector search
LLM/agent usage
```

Out of scope:

```txt
frontend dashboard
public API wrapper
user authentication
portfolio management UI
charting UI
manual watchlist management UI
```

The system should be designed as a **normal deterministic bot with selective agentic modules**, not as a fully autonomous agent.

---

# 2. Core Design Philosophy

The bot should not be an “article summarizer.”

It should be an **event detection and market impact system**.

The correct mental model:

```txt
Detect possible market event
→ cluster related reports
→ verify / classify / score
→ decide whether to alert
→ preserve compact event history
```

Not:

```txt
Fetch article
→ summarize article
→ alert user
```

This distinction matters because:

```txt
many sources are paywalled
headlines/snippets are often enough for detection
multiple sources may report the same event
the user should not receive duplicate alerts
official sources are more reliable than media commentary
```

The bot should ingest a lot of information but interrupt the user rarely.

---

# 3. Recommended High-Level Architecture

```txt
Source Registry
   ↓
Collectors
   ↓
Raw Ingestion Store
   ↓
Normalizer
   ↓
Deduper
   ↓
Entity Extractor
   ↓
Embedding / Similarity Search
   ↓
Event Clusterer
   ↓
Market Data Joiner
   ↓
Scoring Engine
   ↓
Alert Policy Engine
   ↓
Alert Dispatcher / Digest Builder
   ↓
Retention Jobs
```

Agentic investigation should sit on the side:

```txt
                    ┌─────────────────────┐
                    │ Agentic Investigator │
                    └─────────▲───────────┘
                              │
Triggered only by high-value / uncertain events
                              │
News → Cluster → Score → Alert Policy
```

---

# 4. Bot vs Agent Design Choice

## Recommended approach

Use:

```txt
Deterministic bot for the core pipeline
Agentic module for selective investigation
```

Do **not** make every headline go through an autonomous agent.

## Deterministic bot should handle

```txt
RSS polling
API polling
source scheduling
normalization
URL canonicalization
duplicate detection
basic entity extraction
basic classification
event clustering
scoring
alert routing
database retention
```

## Agentic module should handle

```txt
unclear but potentially important events
single-source high-impact reports
price moves without obvious catalyst
confirmation search
official source lookup
deeper “why does this matter?” explanation
missed-catalyst review
```

## Agent trigger examples

Trigger the agent only when:

```txt
news_score is high but confidence is low
single-source event affects watchlist asset
large price move has no known catalyst
headline implies regulatory / geopolitical / central bank surprise
event cluster changed status from rumor → reported → official
official disclosure needs interpretation
```

Avoid:

```txt
every article → agent → research → summarize → decide
```

That is expensive, slow, and noisy.

---

# 5. Source Strategy

The system should support multiple source types.

```ts
type SourceType =
  | "rss"
  | "api"
  | "crawler"
  | "official"
  | "newsletter"
  | "social"
  | "market_data";
```

## Source tiers

Use source quality tiers for scoring.

```txt
100 = official regulator / central bank / exchange / company filing
90  = paid institutional wire/API, if used
75  = reputable financial media
60  = aggregator result
40  = blog/social/Telegram/Discord
20  = unverified source
```

## Source categories

```ts
type SourceCategory =
  | "global_macro"
  | "us_equity"
  | "vietnam_equity"
  | "crypto"
  | "commodity"
  | "fx"
  | "rates"
  | "geopolitics"
  | "company_disclosure"
  | "exchange_announcement";
```

## Recommended source layers

### Layer 1: Official sources

Highest priority.

Examples:

```txt
Fed
BLS
BEA
US Treasury
EIA
SEC filings
ECB
BOJ
BOE
PBOC
SBV
HOSE
HNX
SSC
company disclosure pages
company investor relations pages
crypto exchange announcements
protocol foundation blogs
```

Official sources should have the highest trust score and can trigger immediate alerts if relevant.

### Layer 2: Free financial media

Examples:

```txt
Investing.com RSS
MarketWatch RSS
Yahoo Finance
CNBC
AP
BBC
Nikkei Asia
Vietstock
Stockbiz
CoinDesk
Cointelegraph
The Defiant
CryptoSlate
```

These are useful as early signals but should usually be verified or clustered.

### Layer 3: Aggregators

Examples:

```txt
Google News RSS keyword feeds
GDELT
NewsAPI-style services
NewsData.io
Finnhub
Alpha Vantage news
```

Aggregators are useful for coverage, but their output should be treated as signal, not canonical truth.

### Layer 4: Personal paid/newsletter signals

For personal use, the system may ingest:

```txt
paywalled headlines
RSS teaser text
email newsletters
subscription alerts
Google News snippets
personal notification emails
```

Important rule:

```txt
Do not depend on full article text.
Do not bypass paywalls.
Do not store paywalled article bodies long-term.
```

Use paywalled sources as:

```txt
headline/snippet signal
→ search/verify elsewhere
→ cluster with accessible sources
→ summarize only accessible evidence
```

---

# 6. Source Registry

Maintain source configuration in the database or config file.

```ts
type NewsSource = {
  id: string;
  name: string;
  type: SourceType;
  category: SourceCategory;
  region: "global" | "asia" | "us" | "vietnam" | "china" | "crypto" | "other";
  assetClasses: AssetClass[];

  url: string;
  language: "en" | "vi" | "zh" | "ja" | "multi";

  enabled: boolean;
  pollingIntervalSeconds: number;

  sourceScore: number;
  paywallRisk: "none" | "partial" | "high";
  requiresAuth: boolean;

  parserType: "rss" | "html_metadata" | "json_api" | "custom";
  rateLimitPerHour?: number;

  createdAt: Date;
  updatedAt: Date;
};
```

Recommended polling intervals:

```txt
Official macro feeds:       1–5 min near scheduled releases, otherwise 15–60 min
Financial RSS:              3–10 min
Google News RSS:            10–30 min
Vietnam market sources:     5–15 min during market hours
Crypto exchange notices:    1–5 min
Social/Telegram, if used:   1–5 min but low trust
```

---

# 7. Ingestion Pipeline

## 7.1 Collector stage

Collectors fetch source content and store the unmodified result.

Each fetch should create a fetch log.

```ts
type SourceFetchLog = {
  id: string;
  sourceId: string;
  fetchedAt: Date;

  status: "success" | "partial" | "failed";
  httpStatus?: number;
  errorMessage?: string;

  itemCount?: number;
  durationMs: number;

  contentHash?: string;
};
```

Fetch logs are short-lived debugging data.

Recommended retention:

```txt
Fetch logs: 14–30 days
```

## 7.2 Raw ingestion store

Store raw feed items before normalization.

```ts
type RawNewsItem = {
  id: string;
  sourceId: string;

  rawTitle?: string;
  rawDescription?: string;
  rawContent?: string;
  rawUrl?: string;
  rawPublishedAt?: string;
  rawAuthor?: string;

  rawPayload: unknown;

  fetchedAt: Date;
  contentHash: string;
};
```

This layer is for debugging and replaying parsers.

Recommended retention:

```txt
Raw feed items: 30–90 days
Default: 60 days
```

---

# 8. Normalized News Item

Normalize raw feed data into a clean internal structure.

```ts
type NormalizedNewsItem = {
  id: string;
  sourceId: string;

  title: string;
  snippet?: string;
  url: string;
  canonicalUrl?: string;

  sourceName: string;
  sourceType: SourceType;
  sourceScore: number;

  publishedAt?: Date;
  fetchedAt: Date;

  language: "en" | "vi" | "zh" | "ja" | "unknown";
  region: "global" | "asia" | "us" | "vietnam" | "china" | "crypto" | "other";

  assetClasses: AssetClass[];

  isPaywalled?: boolean;
  fullTextAvailable: boolean;

  titleHash: string;
  canonicalUrlHash?: string;
  normalizedTextHash: string;

  processingStatus:
    | "new"
    | "normalized"
    | "deduped"
    | "clustered"
    | "ignored"
    | "failed";

  createdAt: Date;
  updatedAt: Date;
};
```

```ts
type AssetClass =
  | "equity"
  | "crypto"
  | "fx"
  | "rates"
  | "commodity"
  | "macro"
  | "credit"
  | "real_estate";
```

## Normalization rules

Apply:

```txt
trim whitespace
decode HTML entities
normalize Unicode
remove tracking parameters from URLs
canonicalize source URLs
normalize publishedAt into UTC
detect language
infer source region/category
remove boilerplate prefixes
```

Example URL cleanup:

```txt
remove:
utm_source
utm_medium
utm_campaign
fbclid
gclid
ref
```

---

# 9. Paywall Handling

The system should support paywalled sources without requiring full article access.

Allowed data:

```txt
headline
URL
source
published timestamp
RSS description
public teaser
meta description
OpenGraph description
JSON-LD metadata
Google News snippet
newsletter excerpt personally received
```

Avoid:

```txt
paywall bypassing
unofficial mirrors
long-term storage of full paid article bodies
building core alerts around full paywalled content
```

## Paywall-aware item fields

```ts
type PaywallMetadata = {
  isPaywalled: boolean;
  paywallRisk: "none" | "partial" | "high";
  publicSnippetAvailable: boolean;
  fullTextStored: boolean;
  signalOnly: boolean;
};
```

For paywalled items:

```txt
signalOnly = true
fullTextStored = false
```

The bot should then use the item as a weak/medium signal and search for confirmation from:

```txt
official source
free media source
market data reaction
related existing event cluster
```

---

# 10. Deduplication

Deduplication should happen at multiple levels.

## 10.1 Exact dedupe

Use:

```txt
canonical URL hash
title hash
source item GUID
content hash
```

If the same source republishes the same item, suppress it.

## 10.2 Near-duplicate dedupe

Use:

```txt
normalized title similarity
entity overlap
published time window
embedding similarity
same source family
```

Example duplicate cluster:

```txt
"Oil rises after tanker incident"
"Crude jumps as Middle East shipping risks rise"
"Brent gains on Gulf tanker reports"
```

These should become one event cluster, not three alerts.

## 10.3 Recommended dedupe logic

```txt
1. If canonicalUrlHash already exists → exact duplicate
2. Else if titleHash exists within 30 days → duplicate
3. Else if embedding similarity > threshold and entity overlap high → attach to existing cluster
4. Else create candidate new event
```

Suggested thresholds:

```txt
same URL: exact duplicate
same normalized title: duplicate
embedding similarity > 0.88: likely duplicate
embedding similarity 0.78–0.88: related, needs cluster decision
embedding similarity < 0.78: probably new
```

These thresholds should be calibrated later.

---

# 11. Entity Extraction

Extract market-relevant entities from title/snippet.

```ts
type NewsEntity = {
  id: string;
  newsItemId: string;

  entityType:
    | "company"
    | "ticker"
    | "crypto_token"
    | "country"
    | "central_bank"
    | "commodity"
    | "currency"
    | "index"
    | "sector"
    | "person"
    | "regulator"
    | "exchange"
    | "protocol";

  rawText: string;
  normalizedName: string;

  ticker?: string;
  exchange?: string;
  country?: string;

  confidence: number;
};
```

## Extraction methods

Use a hybrid approach:

```txt
rule-based ticker/entity dictionaries
watchlist matching
known company aliases
known crypto token aliases
LLM extraction for high-value ambiguous items
```

For Vietnam, keep a strong alias table:

```txt
Vingroup → VIC
Vinhomes → VHM
VinFast → VFS
Vinamilk → VNM
Hoa Phat → HPG
FPT → FPT
VN-Index → VNINDEX
VN30 → VN30
```

For crypto:

```txt
Bitcoin → BTC
Ethereum → ETH
Solana → SOL
Tether → USDT
Hyperliquid → HYPE / protocol entity
Binance → exchange entity, not always BNB
```

---

# 12. Embeddings and Vector Index

## Recommendation

Use embeddings, but not as a replacement for LLMs.

```txt
Embeddings/vector index = memory + similarity + retrieval + dedupe
LLM = reasoning + classification + summarization + judgment
```

Since the system already uses Postgres, use:

```txt
Postgres + pgvector
```

Avoid adding Qdrant/Pinecone/Weaviate at the beginning unless scale demands it.

## What to embed

Do not embed full paywalled article text.

Embed compact public text:

```txt
title
snippet
source
entities
asset classes
region
```

Example embedding text:

```txt
Title: China weighs new property support package.
Snippet: Beijing is considering measures to stabilize the property sector.
Source: Financial Times.
Entities: China, property developers, stimulus, yuan.
Asset classes: equities, commodities, FX.
```

## Embedding tables

### News item embeddings

```ts
type NewsItemEmbedding = {
  newsItemId: string;
  embeddingModel: string;
  embeddingVersion: string;
  embeddingTextHash: string;
  vector: number[];
  createdAt: Date;
};
```

Used for:

```txt
near-duplicate detection
similar article lookup
short-term clustering
```

### Event cluster embeddings

```ts
type EventClusterEmbedding = {
  eventClusterId: string;
  embeddingModel: string;
  embeddingVersion: string;
  embeddingTextHash: string;
  vector: number[];
  createdAt: Date;
  updatedAt: Date;
};
```

Used for:

```txt
historical event search
related event lookup
missed-catalyst review
topic resurfacing detection
```

## Embedding model versioning

Store model/version because embeddings are not interchangeable.

```ts
type EmbeddingMetadata = {
  modelProvider: "openai" | "google" | "cohere" | "local" | "other";
  modelName: string;
  dimensions: number;
  createdAt: Date;
};
```

If the model changes later:

```txt
old vectors remain usable for old index
new vectors should be generated into a new version
re-embed important long-lived event clusters first
raw old news items do not necessarily need re-embedding
```

Do not worry too much about deprecation as long as you keep:

```txt
embedding text
model name
model version
```

That allows re-embedding if needed.

---

# 13. Event Clustering

The system should treat **event clusters** as first-class objects.

A cluster represents the actual market event, not one article.

```ts
type EventCluster = {
  id: string;

  canonicalHeadline: string;
  summary?: string;

  firstSeenAt: Date;
  lastUpdatedAt: Date;

  status: "rumor" | "reported" | "confirmed" | "official" | "stale" | "resolved";

  regions: string[];
  assetClasses: AssetClass[];
  affectedEntities: string[];
  affectedTickers: string[];

  sourceCount: number;
  topSourceScore: number;
  confirmationScore: number;

  noveltyScore: number;
  urgencyScore: number;
  marketImpactScore: number;
  relevanceScore: number;
  finalScore: number;

  lastAlertedAt?: Date;
  alertLevel?: "none" | "digest" | "watchlist" | "immediate";

  createdAt: Date;
  updatedAt: Date;
};
```

Cluster membership:

```ts
type EventClusterItem = {
  eventClusterId: string;
  newsItemId: string;

  relationType: "duplicate" | "related" | "update" | "confirmation" | "contradiction";

  similarityScore?: number;
  addedAt: Date;
};
```

## Cluster decision logic

For each normalized news item:

```txt
1. Search recent event clusters by embedding similarity
2. Filter by time window
3. Check entity overlap
4. Check topic/category compatibility
5. Decide:
   - duplicate of existing event
   - related update
   - confirmation
   - contradiction
   - new event
```

## Time windows

Suggested event matching windows:

```txt
fast news / crypto:       24–72 hours
macro/geopolitics:        7–30 days
recurring themes:         30–180 days
company disclosures:      30–365 days
Vietnam upgrade themes:   6–24 months
```

Some themes resurface over long periods, so event search should support both:

```txt
recent cluster matching
historical related-event lookup
```

---

# 14. Market Data Join

Market impact scoring improves significantly when joined with price/volume data.

The bot should compare news with market movement.

```ts
type MarketMove = {
  id: string;

  assetSymbol: string;
  assetClass: AssetClass;
  exchange?: string;

  timestamp: Date;
  window: "5m" | "15m" | "1h" | "4h" | "1d";

  priceChangePct: number;
  volumeChangePct?: number;
  valueTradedChangePct?: number;

  zScore?: number;
};
```

Useful joins:

```txt
news about oil + Brent/WTI move
Fed news + DXY / US yields / gold / S&P futures move
Vietnam disclosure + ticker price/volume move
crypto exchange announcement + token price/volume move
geopolitical headline + oil/gold/FX move
```

Immediate alert can trigger when:

```txt
news_score >= 65
AND price_move_score >= 70
```

This helps reduce noise and catches news the market is actually reacting to.

NOTE: market data service should be modular and configurable, support many data providers and extensible.

In this first iteration, use binance/coingecko api for crypto, their free/public tier is good enough.

I am not sure which provider is best for U.S. and commodity market, feel free to suggest some.

For Vietnam stock market data, we already have a dedicated in-house local service here: http://192.168.100.39:8020/docs. For example:

```bash
curl -X 'POST' \
  'http://192.168.100.39:8020/api/v1/stocks/quotes' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "symbols": [
    "vic","vcb"
  ]
}'
```

---

# 15. Scoring Engine

Each event cluster should receive a score based on multiple dimensions.

```ts
type EventScoreBreakdown = {
  sourceScore: number;
  impactScore: number;
  relevanceScore: number;
  noveltyScore: number;
  urgencyScore: number;
  confidenceScore: number;

  duplicatePenalty: number;
  noisePenalty: number;
  stalePenalty: number;

  finalScore: number;
};
```

## Source score

Based on source quality.

```txt
official source: 90–100
tier-1 financial media: 75–90
free finance media: 60–75
aggregator: 45–65
social/blog: 20–50
```

## Impact score

Based on event type.

High impact:

```txt
central bank surprise
inflation/jobs/GDP surprise
war escalation
sanctions
oil/gas/shipping disruption
exchange hack/listing/delisting
trading halt
regulatory change
earnings shock
large company disclosure
index inclusion/market upgrade decision
```

Low impact:

```txt
generic market recap
opinion article
analyst preview
expected event
minor commentary
duplicate coverage
```

## Relevance score

Based on user-specific watchlists.

```txt
Tier A: current holdings
Tier B: active watchlist
Tier C: themes of interest
Tier D: general market context
```

Suggested thresholds:

```txt
Tier A asset: lower alert threshold
Tier B asset: normal-high threshold
Tier C macro theme: high threshold
General news: very high threshold
```

## Novelty score

High novelty:

```txt
first report of a new event
status changes from rumor to official
new major detail
new affected asset
unexpected surprise
```

Low novelty:

```txt
another article repeating same thing
generic update without new information
stale topic resurfacing
```

## Confidence score

Based on confirmation.

```txt
official source → high confidence
multiple reputable media → medium-high confidence
single reputable media → medium confidence
aggregator only → low-medium confidence
social only → low confidence
```

---

# 16. Alert Policy

The system should use alert escalation, not raw news alerts.

## Alert levels

```txt
Level 1: Immediate alert
Level 2: Watchlist batch
Level 3: Daily digest
Level 4: Archive only
```

## Suggested thresholds

```txt
Immediate alert: score >= 80
Watchlist batch: score 55–79
Daily digest: score 30–54
Archive only: score < 30
```

These should be adjustable by category.

Example:

```ts
const alertThresholds = {
  currentHoldings: {
    immediate: 70,
    watchlist: 50,
    digest: 25,
  },
  activeWatchlist: {
    immediate: 80,
    watchlist: 55,
    digest: 30,
  },
  macroThemes: {
    immediate: 85,
    watchlist: 60,
    digest: 35,
  },
  generalMarket: {
    immediate: 90,
    watchlist: 70,
    digest: 40,
  },
};
```

## Immediate alert criteria

Allow immediate alerts when one or more are true:

```txt
official source publishes major event
multiple reputable sources confirm same event
event affects Tier A holding
large price move confirms news relevance
regulatory/exchange/company disclosure is material
crypto exchange listing/delisting/hack affects watched token
central bank/macro release surprises market
```

## Suppression rules

Suppress alerts when:

```txt
event is duplicate
topic is in cooldown period
headline is generic commentary
source quality is low
no affected asset/entity is detected
event is stale
price/news reaction is weak
```

## Cooldown

Per event/topic cooldown:

```txt
3–6 hours for recurring macro/geopolitical themes
30–60 minutes for high-volatility crypto events
1 trading session for generic company commentary
```

Allow alert despite cooldown if:

```txt
status escalates
official confirmation appears
price move crosses threshold
new material detail appears
affected asset changes materially
```

---

# 17. Alert Record

Every alert decision should be stored, including suppressed decisions.

```ts
type AlertDecision = {
  id: string;
  eventClusterId: string;

  decision:
    | "immediate_alert"
    | "watchlist_batch"
    | "daily_digest"
    | "archive_only"
    | "suppressed";

  reason: string;

  scoreBreakdown: EventScoreBreakdown;

  sentAt?: Date;
  channel?: "telegram" | "email" | "discord" | "dashboard" | "log";

  suppressionReason?: string;

  createdAt: Date;
};
```

This is important for debugging:

```txt
Why did the bot alert this?
Why did the bot suppress this?
What did it miss?
```

---

# 18. Alert Message Format

Immediate alerts should be short and structured.

```txt
[Immediate Market Alert]

Event:
Oil jumps after reported shipping incident near Hormuz

Status:
Reported by multiple media, not yet official

Affected:
Brent, WTI, energy stocks, airlines, inflation expectations

Market reaction:
Brent +3.8% over 1h

Confidence:
Medium-high

Why it matters:
Potential disruption risk to Gulf shipping and energy supply.

Sources:
Reuters, Investing.com, Google News cluster
```

Avoid long summaries unless requested.

The bot should distinguish:

```txt
reported
confirmed
official
rumor
market reaction only
```

---

# 19. Digest Logic

The digest should group by event clusters, not articles.

Suggested digest sections:

```txt
Global macro
US equities
Vietnam market
Crypto
Commodities
FX/rates
Watchlist-specific events
Missed-catalyst review
```

Each digest item:

```txt
event headline
status
score
affected assets
1–3 bullet summary
source count
important update since previous digest
```

---

# 20. Missed-Catalyst Review

This is critical for avoiding missed important news while keeping alerts strict.

At end of day or after each market session, compare:

```txt
large price movers
vs
event clusters detected around the move
```

Example checks:

```txt
BTC moved +7%
Did the bot identify a relevant crypto event?

VIC fell -5%
Did the bot detect disclosure, foreign flow, sector news, or index news?

Brent rose +4%
Did the bot detect oil/geopolitical/supply catalyst?
```

If no matching event exists, create a review task:

```ts
type MissedCatalystReview = {
  id: string;

  assetSymbol: string;
  assetClass: AssetClass;
  moveWindow: "1h" | "4h" | "1d";
  priceChangePct: number;
  volumeChangePct?: number;

  detectedEventClusterId?: string;

  status: "pending" | "investigating" | "resolved" | "no_clear_catalyst";

  agentSummary?: string;
  createdAt: Date;
  updatedAt: Date;
};
```

This review can trigger the agentic investigator.

---

# 21. Agentic Investigator

The agent should be a constrained module, not the main pipeline.

## Inputs

```ts
type InvestigationRequest = {
  eventClusterId?: string;
  assetSymbol?: string;
  question: string;

  maxSourcesToCheck: number;
  allowedSourceTypes: SourceType[];

  deadlineSeconds?: number;
};
```

## Outputs

```ts
type InvestigationResult = {
  status:
    | "confirmed"
    | "likely"
    | "unclear"
    | "false_signal"
    | "no_clear_catalyst";

  confidence: number;

  summary: string;
  affectedAssets: string[];
  importantSources: string[];

  recommendedAlertLevel:
    | "none"
    | "digest"
    | "watchlist"
    | "immediate";

  reasoningNotesForLog: string;
};
```

## Agent tools

The agent may use:

```txt
search internal news database
search recent event clusters
query market price data
query official sources
query RSS/archive data
search web/news API, if configured
summarize event cluster
```

Do not allow the agent to:

```txt
send alerts directly without policy engine
modify source config
delete data
bypass paywalls
trade
place orders
change portfolio state
```

Agent output should go back into the deterministic alert policy engine.

---

# 22. Retention Policy

Use different retention for different data layers.

Recommended defaults:

```txt
Fetch logs:              14 days
Raw news items:          60 days
Normalized news items:   180 days
News item embeddings:    180 days
Event clusters:          3 years
Event embeddings:        3 years
High-impact alerts:      forever
Suppressed decisions:    180 days
Full article text:       avoid storing, or 7–30 days max
```

## Suggested retention config

```ts
const retentionPolicy = {
  fetchLogsDays: 14,
  rawFeedItemsDays: 60,
  normalizedNewsItemsDays: 180,
  newsItemEmbeddingsDays: 180,

  eventClustersDays: 365 * 3,
  eventClusterEmbeddingsDays: 365 * 3,

  alertDecisionsDays: 365,
  highImpactAlertsDays: null,

  fullTextCacheDays: 14,
};
```

## Why not keep only 1 week?

Too short. You lose:

```txt
dedupe memory
recurring topic context
debugging history
missed alert review
event backtesting data
```

## Why not keep raw data forever?

Not useful and creates:

```txt
storage bloat
slower dedupe/search
copyright/paywall concerns
messy old data
harder migrations/backups
```

Keep compact event history instead.

---

# 23. Database Design Overview

Recommended tables:

```txt
news_sources
source_fetch_logs
raw_news_items
normalized_news_items
news_entities
news_item_embeddings

event_clusters
event_cluster_items
event_cluster_embeddings
event_score_history

market_moves
alert_decisions
alert_deliveries
missed_catalyst_reviews

watchlists
watchlist_entities
retention_jobs
```

## Watchlist tables

```ts
type WatchlistEntity = {
  id: string;

  symbol?: string;
  name: string;

  entityType:
    | "stock"
    | "crypto"
    | "commodity"
    | "currency"
    | "index"
    | "macro_theme"
    | "country"
    | "sector";

  tier: "A" | "B" | "C" | "D";

  region?: string;
  assetClass?: AssetClass;

  aliases: string[];

  enabled: boolean;

  createdAt: Date;
  updatedAt: Date;
};
```

Example watchlist tiers:

```txt
Tier A: current holdings
Tier B: active watchlist
Tier C: macro themes
Tier D: general context
```

---

# 24. Processing Jobs

Recommended job structure:

## Frequent jobs

```txt
poll_sources
normalize_raw_items
dedupe_news_items
extract_entities
generate_embeddings
cluster_events
score_event_clusters
dispatch_immediate_alerts
```

## Periodic jobs

```txt
build_watchlist_digest
build_daily_digest
run_missed_catalyst_review
refresh_source_health
cleanup_retention
recompute_event_scores
```

## Suggested cadence

```txt
poll crypto exchange announcements: 1–5 min
poll major RSS feeds: 3–10 min
poll Google News RSS: 10–30 min
normalize/dedupe: continuous or every 1–5 min
score clusters: continuous or every 1–5 min
digest: scheduled
retention cleanup: daily
missed-catalyst review: after market close / every few hours for crypto
```

---

# 25. LLM Usage

Use LLMs selectively.

## Good LLM tasks

```txt
classify event type
extract affected assets from ambiguous headlines
summarize event clusters
estimate market relevance
detect whether new item is material update or duplicate
write concise alert explanation
perform investigation on selected events
```

## Bad LLM tasks

```txt
poll every source
parse every RSS feed
dedupe every item from scratch
store memory
handle routine scheduling
decide everything without deterministic rules
```

## LLM cost control

Only call LLM when:

```txt
source score is high enough
watchlist entity detected
embedding cluster ambiguity exists
event score may cross alert threshold
daily digest generation
agentic investigation requested
```

Do not call LLM on:

```txt
obvious duplicate
low-quality source
generic market recap
old/stale article
items below minimum relevance threshold
```

---

# 26. MVP Implementation Plan

## Phase 1: Deterministic ingestion and storage

Build:

```txt
source registry
RSS collector
raw_news_items table
normalized_news_items table
canonical URL dedupe
basic title hashing
basic source scoring
basic watchlist entity matching
simple alert thresholds
daily digest
```

No embeddings required yet.

## Phase 2: Event clustering

Add:

```txt
event_clusters
event_cluster_items
entity extraction
near-duplicate title similarity
cluster-based alerts
cooldown rules
alert decision logging
```

## Phase 3: pgvector

Add:

```txt
news item embeddings
event cluster embeddings
similarity-based clustering
historical event lookup
topic resurfacing detection
```

Use pgvector inside Postgres.

## Phase 4: Market data join

Add:

```txt
price movement detection
volume/value-traded anomaly detection
news + price confirmation
missed-catalyst review
```

This is where alert quality improves significantly.

## Phase 5: Agentic investigator

Add selective agent workflows for:

```txt
high-impact low-confidence events
large unexplained price moves
watchlist asset investigations
official disclosure interpretation
```

The agent should not replace the core pipeline.

---

# 27. Recommended Defaults

## Retention

```txt
Raw:          60 days
Normalized:   180 days
Clusters:     3 years
Alerts:       forever
Fetch logs:   14 days
Full text:    avoid, or 14 days max
```

## Alert thresholds

```txt
Immediate:    80+
Watchlist:    55–79
Digest:       30–54
Archive:      <30
```

## Similarity thresholds

```txt
Embedding > 0.88: likely duplicate
Embedding 0.78–0.88: related / needs cluster decision
Embedding < 0.78: likely new
```

## Source scoring

```txt
Official:       90–100
Tier-1 media:   75–90
Free media:     60–75
Aggregator:     45–65
Social/blog:    20–50
```

## Cooldowns

```txt
Macro/geopolitics topic: 3–6 hours
Crypto urgent event:    30–60 minutes
Company commentary:     1 trading session
Duplicate headlines:    suppress
```

---

# 28. Key Design Decisions

## 1. Event-first, not article-first

Store articles, but alert on events.

```txt
many articles → one cluster → one alert
```

## 2. Paywall-aware, not paywall-dependent

Use:

```txt
headline
snippet
metadata
source
timestamp
cross-source verification
```

Do not rely on full article bodies.

## 3. Use pgvector, not a separate vector DB initially

Since Postgres is already part of your stack, pgvector is good enough for:

```txt
dedupe
clustering
related event lookup
historical search
```

Avoid Qdrant/Pinecone until needed.

## 4. LLM for judgment, embeddings for memory

```txt
Embeddings find related things.
LLM reasons about them.
```

## 5. Deterministic core, agentic edge

The system should be boring and reliable by default.

Use agents only when there is a high-value question.

## 6. Alert suppression is as important as alert detection

The bot’s job is not to send everything. It should:

```txt
store everything
cluster aggressively
alert selectively
digest the rest
review missed catalysts
```

---

# 29. Final Recommended Architecture

```txt
                    ┌────────────────────┐
                    │   Source Registry   │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │     Collectors      │
                    │ RSS/API/Crawler/etc │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │   Raw News Store    │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │    Normalizer       │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ Exact Deduplication │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Entity Extraction  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ Embedding / pgvector│
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │   Event Clustering  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ Market Data Join    │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │   Scoring Engine    │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ Alert Policy Engine │
                    └──────┬───────┬─────┘
                           │       │
              ┌────────────▼─┐   ┌─▼────────────────┐
              │ Alert/Digest  │   │ Agentic Investigator│
              └──────────────┘   └──────────────────┘
```

Best final design:

```txt
Normal bot handles the pipeline.
pgvector handles memory/similarity.
LLM handles judgment/summarization.
Agent handles selective investigation.
Alert policy controls interruption.
Retention jobs keep the system clean.
```

This gives you a market watch bot that is:

```txt
low-noise
paywall-resistant
debuggable
cheap enough for personal use
expandable across global / Vietnam / crypto markets
able to catch important events without drowning you in alerts
```
