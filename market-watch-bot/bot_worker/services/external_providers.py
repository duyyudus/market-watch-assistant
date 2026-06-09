from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import ProviderCooldown
from common.external_providers import (
    PROVIDER_RETRY_POLICIES,
    ProviderRetryPolicy,
    RateLimitCooldown,
    request_with_retry,
    retry_after_seconds,
)

__all__ = [
    "PROVIDER_RETRY_POLICIES",
    "ProviderRetryPolicy",
    "RateLimitCooldown",
    "provider_is_cooling_down",
    "record_provider_cooldown",
    "request_with_retry",
    "retry_after_seconds",
]


async def record_provider_cooldown(
    session: AsyncSession,
    cooldown: RateLimitCooldown,
) -> ProviderCooldown:
    record = await session.get(ProviderCooldown, cooldown.provider)
    if record is None:
        record = ProviderCooldown(
            provider=cooldown.provider,
            reason=cooldown.reason,
            http_status=cooldown.http_status,
            cooldown_until=cooldown.cooldown_until,
            last_observed_at=cooldown.observed_at,
        )
        session.add(record)
    else:
        record.status = "cooling_down"
        record.reason = cooldown.reason
        record.http_status = cooldown.http_status
        record.cooldown_until = cooldown.cooldown_until
        record.last_observed_at = cooldown.observed_at
    return record


async def provider_is_cooling_down(
    session: AsyncSession,
    provider: str,
    *,
    now: datetime | None = None,
) -> bool:
    record = await session.get(ProviderCooldown, provider)
    if record is None:
        return False
    current = now or datetime.now(UTC)
    if record.cooldown_until <= current:
        record.status = "expired"
        return False
    return record.status == "cooling_down"
