from fastapi import APIRouter

from api_server.app.api.routers import (
    alerts,
    bot,
    digests,
    events,
    health,
    investigations,
    jobs,
    maintenance,
    market,
    news,
    settings,
    sources,
    watchlist,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(bot.router)
router.include_router(jobs.router)
router.include_router(sources.router)
router.include_router(events.router)
router.include_router(news.router)
router.include_router(alerts.router)
router.include_router(digests.router)
router.include_router(market.router)
router.include_router(investigations.router)
router.include_router(watchlist.router)
router.include_router(settings.router)
router.include_router(maintenance.router)

__all__ = ["router"]

