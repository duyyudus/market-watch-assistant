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

export function LLMRunsTab() {
  const [runs, setRuns] = useState<LLMRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const [statusFilter, setStatusFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchLLMRuns = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceLLMRuns(limit, offset);
      setRuns(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err?.message || "Failed to load LLM runs diagnostics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLLMRuns();
  }, [offset]);

  const filteredItems = runs.filter((run) => {
    if (statusFilter !== "all" && run.status !== statusFilter) return false;
    return true;
  });

  const { items: sortedItems, requestSort, sortConfig } = useSortableData(filteredItems, {
    key: "created_at",
    direction: "desc",
  });

  const currentSortKey = sortConfig?.key || "";
  const currentDirection = sortConfig?.direction || "desc";

  return (
    <Panel title="LLM Execution Diagnostics">
      {error ? (
        <SectionError title="Failed to load LLM diagnostics" message={error} retry={fetchLLMRuns} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border border-zinc-800/40 bg-zinc-950/20 p-4 rounded-lg">
            <div className="text-sm text-zinc-400">
              Audit agent reasoning pathways, token consumption, and generation snapshots.
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-zinc-500">Status:</span>
              <div className="btn-group border border-zinc-800 rounded-lg p-0.5 bg-zinc-900 flex overflow-hidden">
                {["all", "succeeded", "failed", "pending"].map((status) => (
                  <button
                    key={status}
                    className={`btn btn-xs border-0 rounded ${
                      statusFilter === status ? "bg-indigo-600/90 text-white hover:bg-indigo-600" : "bg-transparent text-zinc-400 hover:text-zinc-200"
                    }`}
                    onClick={() => setStatusFilter(status)}
                    type="button"
                  >
                    {status}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {loading ? (
            <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>
          ) : sortedItems.length === 0 ? (
            <EmptyState icon={Brain} title="No LLM runs recorded" body="No diagnostics log available." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th></th>
                    <SortableHeader label="Run ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="id" onSort={requestSort} />
                    <SortableHeader label="Target" currentSortKey={currentSortKey} direction={currentDirection} sortKey="target_type" onSort={requestSort} />
                    <SortableHeader label="Provider & Model" currentSortKey={currentSortKey} direction={currentDirection} sortKey="model" onSort={requestSort} />
                    <SortableHeader label="Status" currentSortKey={currentSortKey} direction={currentDirection} sortKey="status" onSort={requestSort} />
                    <SortableHeader label="Token Usage" currentSortKey={currentSortKey} direction={currentDirection} sortKey="usage" onSort={requestSort} />
                    <SortableHeader label="Time" currentSortKey={currentSortKey} direction={currentDirection} sortKey="created_at" onSort={requestSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {sortedItems.map((run) => {
                    const isExpanded = expandedId === run.id;
                    const tokens = run.usage;
                    const hasTokenDetail = tokens && (tokens.prompt_tokens != null || tokens.completion_tokens != null);

                    return (
                      <React.Fragment key={run.id}>
                        <tr className="hover:bg-zinc-800/10 transition-colors">
                          <td>
                            <button
                              className="btn btn-ghost btn-xs text-zinc-400 hover:text-white"
                              onClick={() => setExpandedId(isExpanded ? null : run.id)}
                              type="button"
                            >
                              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                          </td>
                          <td className="font-mono text-xs text-zinc-500">{run.id}</td>
                          <td>
                            <div className="flex flex-col">
                              <span className="text-zinc-200 font-semibold text-xs uppercase tracking-wide">
                                {run.target_type}
                              </span>
                              <span className="font-mono text-xxs text-zinc-500 truncate max-w-[120px]" title={run.target_id}>
                                {run.target_id}
                              </span>
                            </div>
                          </td>
                          <td>
                            <div className="flex flex-col text-xs">
                              <span className="text-zinc-400 font-medium">{run.provider}</span>
                              <span className="text-indigo-400 font-semibold">{run.model}</span>
                            </div>
                          </td>
                          <td>
                            <Badge
                              tone={
                                run.status === "succeeded"
                                  ? "success"
                                  : run.status === "failed"
                                  ? "error"
                                  : "warning"
                              }
                            >
                              {run.status}
                            </Badge>
                          </td>
                          <td className="font-mono text-xs">
                            {hasTokenDetail ? (
                              <div className="flex flex-col gap-0.5 text-xxs">
                                <span>In: <strong className="text-zinc-200">{tokens.prompt_tokens}</strong></span>
                                <span>Out: <strong className="text-zinc-200">{tokens.completion_tokens}</strong></span>
                                <span className="border-t border-zinc-800 mt-0.5 pt-0.5 font-bold text-indigo-400">
                                  Total: {tokens.total_tokens}
                                </span>
                              </div>
                            ) : tokens ? (
                              <span className="text-zinc-400 text-xxs italic">Expand JSON...</span>
                            ) : (
                              <span className="text-zinc-600">—</span>
                            )}
                          </td>
                          <td className="text-zinc-400 text-xs">
                            {new Date(run.created_at).toLocaleString()}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-zinc-950/30">
                            <td colSpan={7} className="p-4 border-l-2 border-indigo-500">
                              <div className="space-y-4">
                                <div className="grid gap-4 md:grid-cols-2 text-xs">
                                  <div>
                                    <span className="text-xxs uppercase tracking-wider text-zinc-500 block font-bold mb-1">
                                      Prompt Specifications
                                    </span>
                                    <div className="bg-zinc-900 border border-zinc-800 rounded p-2 text-zinc-300 font-mono text-xxs space-y-1">
                                      <div><span className="text-zinc-500">Version:</span> {run.prompt_version}</div>
                                      <div><span className="text-zinc-500">Hash:</span> {run.prompt_hash}</div>
                                    </div>
                                  </div>
                                  <div>
                                    <span className="text-xxs uppercase tracking-wider text-zinc-500 block font-bold mb-1">
                                      Token Details / JSON
                                    </span>
                                    <pre className="bg-zinc-900 border border-zinc-800 rounded p-2 text-zinc-300 font-mono text-xxs overflow-x-auto max-h-16">
                                      {JSON.stringify(run.usage || {}, null, 2)}
                                    </pre>
                                  </div>
                                </div>

                                {run.error_message && (
                                  <div>
                                    <span className="text-xxs uppercase tracking-wider text-rose-500 block font-bold mb-1">
                                      Execution Failure Error
                                    </span>
                                    <div className="mockup-code bg-rose-950/15 border border-rose-900/30 text-rose-300 text-xs p-3 font-mono">
                                      {run.error_message}
                                    </div>
                                  </div>
                                )}

                                <div className="grid gap-4 md:grid-cols-2">
                                  <div>
                                    <span className="text-xxs uppercase tracking-wider text-zinc-500 block font-bold mb-1">
                                      Input Parameters Snapshot
                                    </span>
                                    <pre className="bg-zinc-950 border border-zinc-800 rounded p-3 text-zinc-400 font-mono text-xxs overflow-auto max-h-56">
                                      {JSON.stringify(run.input_snapshot || {}, null, 2)}
                                    </pre>
                                  </div>
                                  <div>
                                    <span className="text-xxs uppercase tracking-wider text-zinc-500 block font-bold mb-1">
                                      LLM Output / Result Snapshot
                                    </span>
                                    <pre className="bg-zinc-950 border border-zinc-800 rounded p-3 text-zinc-300 font-mono text-xxs overflow-auto max-h-56">
                                      {JSON.stringify(run.result || {}, null, 2)}
                                    </pre>
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between border-t border-zinc-800/40 pt-4">
            <div className="text-xs text-zinc-500">
              Showing <span className="font-semibold text-zinc-300">{sortedItems.length}</span> of{" "}
              <span className="font-semibold text-zinc-300">{total}</span> total LLM analyses runs
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

/* ==========================================
   TAB 6: LLM COSTS
   ========================================== */
