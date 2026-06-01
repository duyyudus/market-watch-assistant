from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class PipelineStageMetric:
    stage_name: str
    start_time: datetime
    end_time: datetime
    duration_ms: int
    items_in: int | None = None
    items_out: int | None = None
    status: str = "success"

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_name": self.stage_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms,
            "items_in": self.items_in,
            "items_out": self.items_out,
            "status": self.status,
        }


@dataclass
class PipelineRunMetrics:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    stages: list[PipelineStageMetric] = field(default_factory=list)
    status: str = "success"

    def record_stage(
        self,
        *,
        stage_name: str,
        start_time: datetime,
        end_time: datetime,
        items_in: int | None = None,
        items_out: int | None = None,
        status: str = "success",
    ) -> PipelineStageMetric:
        metric = PipelineStageMetric(
            stage_name=stage_name,
            start_time=start_time,
            end_time=end_time,
            duration_ms=max(0, int((end_time - start_time).total_seconds() * 1000)),
            items_in=items_in,
            items_out=items_out,
            status=status,
        )
        self.stages.append(metric)
        if status == "failed":
            self.status = "failed"
        elif status == "degraded" and self.status == "success":
            self.status = "degraded"
        return metric

    def finish(self, *, status: str | None = None) -> None:
        self.completed_at = datetime.now(UTC)
        if status:
            self.status = status

    def to_dict(self) -> dict[str, object]:
        completed = self.completed_at or datetime.now(UTC)
        return {
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": completed.isoformat(),
            "duration_ms": max(0, int((completed - self.started_at).total_seconds() * 1000)),
            "stages": [stage.to_dict() for stage in self.stages],
            "slow_stages": [],
        }


def slow_pipeline_stages(
    current_metrics: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> list[dict[str, object]]:
    durations_by_stage: dict[str, list[int]] = {}
    for result in prior_results:
        metrics = result.get("pipeline_metrics")
        if not isinstance(metrics, dict):
            continue
        stages = metrics.get("stages")
        if not isinstance(stages, list):
            continue
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            name = stage.get("stage_name")
            duration = stage.get("duration_ms")
            if isinstance(name, str) and isinstance(duration, int | float):
                durations_by_stage.setdefault(name, []).append(int(duration))

    slow: list[dict[str, object]] = []
    stages = current_metrics.get("stages", [])
    if not isinstance(stages, list):
        return slow
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        name = stage.get("stage_name")
        duration = stage.get("duration_ms")
        if not isinstance(name, str) or not isinstance(duration, int | float):
            continue
        priors = durations_by_stage.get(name, [])
        if not priors:
            continue
        average = int(sum(priors) / len(priors))
        threshold = average * 2
        if int(duration) > threshold:
            slow.append(
                {
                    "stage_name": name,
                    "duration_ms": int(duration),
                    "average_duration_ms": average,
                    "threshold_ms": threshold,
                }
            )
    return slow
