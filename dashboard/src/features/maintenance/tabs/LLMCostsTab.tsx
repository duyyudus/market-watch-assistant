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

export function LLMCostsTab() {
  const [summary, setSummary] = useState<LLMCostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCosts = async () => {
    try {
      setLoading(true);
      setError(null);
      setSummary(await api.maintenanceLLMCosts());
    } catch (err: any) {
      setError(err?.message || "Failed to load LLM costs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCosts();
  }, []);

  if (error) {
    return <SectionError title="Failed to load LLM costs" message={error} retry={fetchCosts} />;
  }
  if (loading || !summary) {
    return <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>;
  }

  const maxDailyTokens = Math.max(1, ...summary.daily.map((day) => day.total_tokens));

  return (
    <Panel title="LLM Cost Tracking">
      <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-4">
          <CostMetric label="7-Day Tokens" value={formatCompactNumber(summary.weekly.total_tokens)} />
          <CostMetric label="Prompt Tokens" value={formatCompactNumber(summary.weekly.prompt_tokens)} />
          <CostMetric label="Completion Tokens" value={formatCompactNumber(summary.weekly.completion_tokens)} />
          <CostMetric label="Estimated Cost" value={formatCurrency(summary.weekly.estimated_cost_usd)} />
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/30 p-4">
            <div className="mb-4 text-xs font-bold uppercase tracking-wider text-zinc-500">
              Daily Token Trend
            </div>
            {summary.daily.length === 0 ? (
              <EmptyState icon={Brain} title="No token usage" body="No LLM usage has been recorded in the last seven days." />
            ) : (
              <div className="space-y-3">
                {summary.daily.map((day) => (
                  <div key={day.date} className="grid grid-cols-[6rem_1fr_5rem] items-center gap-3 text-xs">
                    <span className="font-mono text-zinc-500">{day.date}</span>
                    <div className="h-2 overflow-hidden rounded-full bg-zinc-900">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{ width: `${Math.max(3, (day.total_tokens / maxDailyTokens) * 100)}%` }}
                      />
                    </div>
                    <span className="text-right font-mono text-zinc-300">
                      {formatCompactNumber(day.total_tokens)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/30 p-4">
            <div className="mb-4 text-xs font-bold uppercase tracking-wider text-zinc-500">
              Usage by Model
            </div>
            <BreakdownRows
              emptyLabel="No model usage"
              items={summary.by_model.map((item) => ({
                key: item.model || "unknown",
                label: item.model || "Unknown model",
                tokens: item.total_tokens,
                cost: item.estimated_cost_usd,
              }))}
            />
          </div>
        </div>

        <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/30 p-4">
          <div className="mb-4 text-xs font-bold uppercase tracking-wider text-zinc-500">
            Usage by Analysis Type
          </div>
          <BreakdownRows
            emptyLabel="No analysis usage"
            items={summary.by_analysis_type.map((item) => ({
              key: item.analysis_type || "unknown",
              label: item.analysis_type || "Unknown analysis",
              tokens: item.total_tokens,
              cost: item.estimated_cost_usd,
            }))}
          />
        </div>
      </div>
    </Panel>
  );
}

/* ==========================================
   TAB 7: PIPELINE METRICS
   ========================================== */
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

function CostMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800/60 bg-zinc-950/30 p-4">
      <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="mt-2 text-2xl font-black text-zinc-100">{value}</div>
    </div>
  );
}

function BreakdownRows({
  emptyLabel,
  items,
}: {
  emptyLabel: string;
  items: Array<{ key: string; label: string; tokens: number; cost: number }>;
}) {
  const maxTokens = Math.max(1, ...items.map((item) => item.tokens));
  if (items.length === 0) {
    return <div className="text-sm text-zinc-500">{emptyLabel}</div>;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.key} className="grid grid-cols-[minmax(0,1fr)_7rem] gap-3 text-xs">
          <div>
            <div className="mb-1 truncate font-medium text-zinc-300" title={item.label}>{item.label}</div>
            <div className="h-2 overflow-hidden rounded-full bg-zinc-900">
              <div
                className="h-full rounded-full bg-indigo-500"
                style={{ width: `${Math.max(3, (item.tokens / maxTokens) * 100)}%` }}
              />
            </div>
          </div>
          <div className="text-right font-mono text-zinc-400">
            <div>{formatCompactNumber(item.tokens)}</div>
            <div>{formatCurrency(item.cost)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function formatCompactNumber(value: number): string {
  return Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function formatCurrency(value: number): string {
  return Intl.NumberFormat(undefined, {
    currency: "USD",
    maximumFractionDigits: 4,
    style: "currency",
  }).format(value);
}

/* ==========================================
   TAB 8: RETENTION HISTORY
   ========================================== */
