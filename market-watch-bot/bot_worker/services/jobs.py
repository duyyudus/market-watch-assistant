from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    JobRun,
)
from bot_worker.services.pipeline_metrics import slow_pipeline_stages


async def record_job_run(
    session: AsyncSession,
    job_name: str,
    result: dict[str, object],
    *,
    status: str = "success",
    error_message: str | None = None,
) -> JobRun:
    if status == "success" and job_name == "pipeline" and isinstance(
        result.get("pipeline_metrics"), dict
    ):
        prior = list(
            (
                await session.scalars(
                    select(JobRun)
                    .where(JobRun.job_name == "pipeline", JobRun.status == "success")
                    .order_by(JobRun.started_at.desc())
                    .limit(20)
                )
            ).all()
        )
        prior_results = [row.result or {} for row in prior]
        metrics = result["pipeline_metrics"]
        assert isinstance(metrics, dict)
        metrics["slow_stages"] = slow_pipeline_stages(metrics, prior_results)
    run = JobRun(
        job_name=job_name,
        status=status,
        completed_at=datetime.now(UTC),
        result=result,
        error_message=error_message,
    )
    session.add(run)
    await session.flush()
    return run
