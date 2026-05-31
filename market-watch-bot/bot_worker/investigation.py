from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from bot_worker.db.models import EventCluster, MissedCatalystReview

if TYPE_CHECKING:
    from bot_worker.config import Settings


OFFICIAL_DOMAINS = (
    "sec.gov",
    "federalreserve.gov",
    "treasury.gov",
    "sbv.gov.vn",
    "ssc.gov.vn",
    "hsx.vn",
    "hnx.vn",
    "binance.com",
    "coinbase.com",
)
HIGH_QUALITY_DOMAINS = (
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "coindesk.com",
    "cointelegraph.com",
)


@dataclass(frozen=True)
class InvestigationConfig:
    enabled: bool = False
    brave_search_api_key: str | None = None
    brave_search_api_key_env: str = "BRAVE_SEARCH_API_KEY"
    max_search_results: int = 10
    max_evidence_items: int = 12
    local_evidence_limit: int = 10
    local_evidence_lookback_days: int = 3
    timeout_seconds: int = 20
    max_concurrency: int = 2
    auto_event_score_threshold: int = 80
    auto_single_source_score_threshold: int = 90
    auto_market_move_score_threshold: int = 70
    auto_rumor_score_threshold: int = 70
    min_modifier: int = -10
    max_modifier: int = 10
    official_domains: tuple[str, ...] = OFFICIAL_DOMAINS
    high_quality_domains: tuple[str, ...] = HIGH_QUALITY_DOMAINS

    @classmethod
    def from_settings(cls, settings: Settings) -> InvestigationConfig:
        api_key = os.environ.get(settings.investigation.brave_search_api_key_env)
        if api_key is None:
            api_key = settings.brave_search_api_key
        return cls(
            enabled=settings.investigation.enabled,
            brave_search_api_key=api_key,
            brave_search_api_key_env=settings.investigation.brave_search_api_key_env,
            max_search_results=settings.investigation.max_search_results,
            max_evidence_items=settings.investigation.max_evidence_items,
            local_evidence_limit=settings.investigation.local_evidence_limit,
            local_evidence_lookback_days=settings.investigation.local_evidence_lookback_days,
            timeout_seconds=settings.investigation.timeout_seconds,
            max_concurrency=settings.investigation.max_concurrency,
            auto_event_score_threshold=settings.investigation.auto_event_score_threshold,
            auto_single_source_score_threshold=(
                settings.investigation.auto_single_source_score_threshold
            ),
            auto_market_move_score_threshold=settings.investigation.auto_market_move_score_threshold,
            auto_rumor_score_threshold=getattr(
                settings.investigation, "auto_rumor_score_threshold", 70
            ),
            min_modifier=settings.investigation.min_modifier,
            max_modifier=settings.investigation.max_modifier,
            official_domains=tuple(
                getattr(settings.investigation, "official_domains", OFFICIAL_DOMAINS)
            ),
            high_quality_domains=tuple(
                getattr(settings.investigation, "high_quality_domains", HIGH_QUALITY_DOMAINS)
            ),
        )


@dataclass(frozen=True)
class BraveSearchResult:
    title: str
    url: str
    description: str
    source_quality: str

    def as_evidence(self) -> dict[str, object]:
        return {
            "kind": "search_result",
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "source_quality": self.source_quality,
        }


def source_quality_for_url(
    url: str,
    official_domains: tuple[str, ...] = OFFICIAL_DOMAINS,
    high_quality_domains: tuple[str, ...] = HIGH_QUALITY_DOMAINS,
) -> str:
    hostname = urlparse(url).hostname or ""
    hostname = hostname.lower().removeprefix("www.")
    if any(hostname == domain or hostname.endswith(f".{domain}") for domain in official_domains):
        return "official"
    if any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in high_quality_domains
    ):
        return "high_quality"
    if hostname:
        return "media"
    return "unknown"


class BraveSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 20,
        http_client_factory: Any = httpx.AsyncClient,
        official_domains: tuple[str, ...] = OFFICIAL_DOMAINS,
        high_quality_domains: tuple[str, ...] = HIGH_QUALITY_DOMAINS,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.http_client_factory = http_client_factory
        self.official_domains = official_domains
        self.high_quality_domains = high_quality_domains

    async def search(self, query: str, *, count: int) -> list[BraveSearchResult]:
        async with self.http_client_factory(timeout=self.timeout_seconds) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
            )
            response.raise_for_status()
        data = response.json()
        results = ((data.get("web") or {}).get("results") or []) if isinstance(data, dict) else []
        normalized: list[BraveSearchResult] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            normalized.append(
                BraveSearchResult(
                    title=str(item.get("title") or ""),
                    url=url,
                    description=str(item.get("description") or ""),
                    source_quality=source_quality_for_url(
                        url,
                        official_domains=self.official_domains,
                        high_quality_domains=self.high_quality_domains,
                    ),
                )
            )
        return normalized


def should_queue_event_investigation(
    event: EventCluster,
    *,
    config: InvestigationConfig,
    market_move_score: int = 0,
) -> bool:
    if not config.enabled:
        return False
    if event.final_score >= config.auto_event_score_threshold:
        return True
    if (
        event.source_count <= 1
        and event.top_source_score >= config.auto_single_source_score_threshold
        and event.final_score >= 55
    ):
        return True
    if market_move_score >= config.auto_market_move_score_threshold and event.final_score >= 55:
        return True
    return (
        event.status in {"rumor", "reported"}
        and event.final_score >= config.auto_rumor_score_threshold
    )


def should_queue_missed_catalyst_investigation(
    review: MissedCatalystReview,
    *,
    config: InvestigationConfig,
) -> bool:
    return bool(
        config.enabled
        and review.status == "pending"
        and review.detected_event_cluster_id is None
    )
