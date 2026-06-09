from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from inspect import isawaitable
from typing import Any

import httpx

Sleeper = Callable[[float], Awaitable[None] | None]
CooldownRecorder = Callable[["RateLimitCooldown"], Awaitable[None] | None]


@dataclass(frozen=True)
class ProviderRetryPolicy:
    max_retries: int
    delays: tuple[float, ...]
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class RateLimitCooldown:
    provider: str
    cooldown_seconds: int
    reason: str
    http_status: int | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def cooldown_until(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.cooldown_seconds)


PROVIDER_RETRY_POLICIES: dict[str, ProviderRetryPolicy] = {
    "rss": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "crawler": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "binance": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "coingecko": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "yahoo_finance": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "vietnam_market": ProviderRetryPolicy(max_retries=2, delays=(5, 15), timeout_seconds=20),
    "brave_search": ProviderRetryPolicy(max_retries=1, delays=(10,), timeout_seconds=20),
    "telegram": ProviderRetryPolicy(max_retries=3, delays=(10, 30, 60), timeout_seconds=20),
    "openrouter_chat": ProviderRetryPolicy(max_retries=1, delays=(30,), timeout_seconds=45),
    "openrouter_embeddings": ProviderRetryPolicy(max_retries=1, delays=(30,), timeout_seconds=30),
}


def retry_after_seconds(response: httpx.Response, fallback: float) -> float:
    value = response.headers.get("Retry-After")
    if value is None:
        return fallback
    try:
        return max(0.0, float(value))
    except ValueError:
        return fallback


async def _sleep(value: float, sleeper: Sleeper) -> None:
    result = sleeper(value)
    if isawaitable(result):
        await result


async def _record(value: RateLimitCooldown, recorder: CooldownRecorder | None) -> None:
    if recorder is None:
        return
    result = recorder(value)
    if isawaitable(result):
        await result


async def request_with_retry(
    *,
    provider: str,
    method: str,
    url: str,
    retry_policy: ProviderRetryPolicy | None = None,
    client: Any,
    sleeper: Sleeper = asyncio.sleep,
    record_cooldown: CooldownRecorder | None = None,
    **kwargs: object,
) -> httpx.Response:
    policy = retry_policy or PROVIDER_RETRY_POLICIES[provider]
    attempts = policy.max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            if hasattr(client, "request"):
                response = await client.request(method, url, **kwargs)
            else:
                response = await getattr(client, method.lower())(url, **kwargs)
            status_code = getattr(response, "status_code", 200)
            if status_code == 429:
                delay = retry_after_seconds(
                    response,
                    policy.delays[min(attempt, len(policy.delays) - 1)] if policy.delays else 0,
                )
                cooldown = RateLimitCooldown(
                    provider=provider,
                    cooldown_seconds=round(delay),
                    reason="rate_limited",
                    http_status=429,
                )
                await _record(cooldown, record_cooldown)
                if attempt < attempts - 1:
                    await _sleep(delay, sleeper)
                    continue
            if status_code != 304 and hasattr(response, "raise_for_status"):
                response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - provider boundary normalizes failures
            last_exc = exc
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code != 429
                and 400 <= exc.response.status_code < 500
            ):
                break
            if attempt >= attempts - 1:
                break
            delay = policy.delays[min(attempt, len(policy.delays) - 1)] if policy.delays else 0
            await _sleep(delay, sleeper)
    assert last_exc is not None
    raise last_exc
