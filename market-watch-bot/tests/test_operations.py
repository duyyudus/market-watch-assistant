from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from bot_worker.db.models import AlertDeliveryRecord, JobRun, LLMAnalysisRun, SourceFetchLog
from bot_worker.services.alert_delivery import AlertDeliveryConfig
from bot_worker.services.operations import run_operational_checks


class OperationSession:
    def __init__(
        self,
        *,
        latest_pipeline: JobRun | None = None,
        source_logs: list[SourceFetchLog] | None = None,
        llm_runs: list[LLMAnalysisRun] | None = None,
        deliveries: list[AlertDeliveryRecord] | None = None,
    ) -> None:
        self.latest_pipeline = latest_pipeline
        self.source_logs = source_logs or []
        self.llm_runs = llm_runs or []
        self.deliveries = deliveries or []
        self.added: list[AlertDeliveryRecord] = []

    def add(self, record: AlertDeliveryRecord) -> None:
        self.added.append(record)
        self.deliveries.append(record)


@pytest.mark.asyncio
async def test_run_operational_checks_records_worker_heartbeat_alert() -> None:
    now = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
    session = OperationSession(
        latest_pipeline=JobRun(
            job_name="pipeline",
            status="success",
            completed_at=now - timedelta(minutes=12),
        )
    )
    settings = SimpleNamespace(bot=SimpleNamespace(polling_interval_seconds=300))

    result = await run_operational_checks(
        session,
        settings=settings,
        alert_delivery_config=AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        now=now,
    )

    assert result["sent"] == 1
    assert result["alerts"] == ["worker_heartbeat"]
    assert session.added[0].channel == "telegram"
    assert "appears to be down" in session.added[0].message_text


@pytest.mark.asyncio
async def test_run_operational_checks_suppresses_duplicate_alerts_within_one_hour() -> None:
    now = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)
    previous = AlertDeliveryRecord(
        channel="telegram",
        recipient="chat_1",
        status="sent",
        message_text=(
            "[Operational Alert]\nworker_heartbeat\n"
            "Market Watch worker appears to be down"
        ),
        attempted_at=now - timedelta(minutes=15),
    )
    session = OperationSession(
        latest_pipeline=JobRun(
            job_name="pipeline",
            status="success",
            completed_at=now - timedelta(minutes=12),
        ),
        deliveries=[previous],
    )
    settings = SimpleNamespace(bot=SimpleNamespace(polling_interval_seconds=300))

    result = await run_operational_checks(
        session,
        settings=settings,
        alert_delivery_config=AlertDeliveryConfig(
            channel="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat_1",
        ),
        now=now,
    )

    assert result["sent"] == 0
    assert result["suppressed"] == 1
    assert session.added == []
