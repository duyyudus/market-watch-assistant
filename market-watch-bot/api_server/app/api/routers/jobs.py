from __future__ import annotations

from fastapi import APIRouter, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import JobRunRead, ListEnvelope
from api_server.app.services import jobs as job_service

router = APIRouter()


@router.get("/jobs/runs", response_model=ListEnvelope[JobRunRead])
async def job_runs(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    name: str | None = None,
) -> ListEnvelope[JobRunRead]:
    rows, total = await job_service.list_job_runs(
        session, limit=limit, offset=offset, name=name
    )
    return ListEnvelope(items=[JobRunRead.model_validate(row) for row in rows], total=total)
