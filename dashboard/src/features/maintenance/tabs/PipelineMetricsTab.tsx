import React, { useEffect, useState } from "react";
import {
  Activity,
  Brain,
  ChevronDown,
  ChevronUp,
  Database,
  History,
  Layers,
  Search,
  Sliders,
  Sparkles,
  Timer,
} from "lucide-react";

import { api } from "../../../api";
import type {
  FetchLog,
  ScoreHistory,
  CatalystReview,
  EmbeddingStats,
  LLMCostSummary,
  LLMRun,
  PipelineMetricsRun,
  RetentionJob,
} from "../../../api";
import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/EmptyState";
import { Panel } from "../../../components/Panel";
import { SectionError } from "../../../components/SectionError";
import { SortableHeader } from "../../../components/SortableHeader";
import { useSortableData } from "../../../hooks/useSortableData";

export function PipelineMetricsTab() {
  const [runs, setRuns] = useState<PipelineMetricsRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const fetchMetrics = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenancePipelineMetrics(limit, offset);
      setRuns(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err?.message || "Failed to load pipeline metrics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, [offset]);

  return (
    <Panel title="Pipeline Performance Metrics">
      {error ? (
        <SectionError title="Failed to load pipeline metrics" message={error} retry={fetchMetrics} />
      ) : loading ? (
        <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>
      ) : runs.length === 0 ? (
        <EmptyState icon={Timer} title="No pipeline metrics" body="Pipeline runs have not recorded stage metrics yet." />
      ) : (
        <div className="space-y-5">
          {runs.map((run) => {
            const maxDuration = Math.max(1, ...run.stages.map((stage) => stage.duration_ms));
            const slowStages = new Set(run.slow_stages.map((stage) => stage.stage_name));
            return (
              <div key={run.job_run_id} className="rounded-lg border border-zinc-800/60 bg-zinc-950/30 p-4">
                <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="font-mono text-xs text-zinc-500">{run.job_run_id}</div>
                    <div className="text-sm text-zinc-300">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : "Unknown start"} · {run.duration_ms} ms
                    </div>
                  </div>
                  <Badge tone={run.status === "success" ? "success" : "warning"}>{run.status}</Badge>
                </div>
                <div className="space-y-3">
                  {run.stages.map((stage) => (
                    <div key={`${run.job_run_id}-${stage.stage_name}`} className="grid gap-2 text-xs md:grid-cols-[12rem_1fr_6rem_5rem] md:items-center">
                      <div className="font-semibold text-zinc-300">{stage.stage_name}</div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-900">
                        <div
                          className={`h-full rounded-full ${slowStages.has(stage.stage_name) ? "bg-amber-500" : "bg-sky-500"}`}
                          style={{ width: `${Math.max(3, (stage.duration_ms / maxDuration) * 100)}%` }}
                        />
                      </div>
                      <div className="font-mono text-zinc-400">{stage.duration_ms} ms</div>
                      <Badge tone={stage.status === "success" ? "success" : stage.status === "failed" ? "error" : "warning"}>
                        {stage.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          <div className="flex items-center justify-between border-t border-zinc-800/40 pt-4">
            <div className="text-xs text-zinc-500">
              Showing <span className="font-semibold text-zinc-300">{runs.length}</span> of{" "}
              <span className="font-semibold text-zinc-300">{total}</span> pipeline runs
            </div>
            <div className="join bg-zinc-900 border border-zinc-800 overflow-hidden">
              <button
                className="btn btn-xs join-item bg-transparent text-zinc-400 border-0 hover:bg-zinc-800"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                type="button"
              >
                Previous
              </button>
              <button
                className="btn btn-xs join-item bg-transparent text-zinc-400 border-0 hover:bg-zinc-800"
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                type="button"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
