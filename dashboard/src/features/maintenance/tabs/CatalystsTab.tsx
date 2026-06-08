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

export function CatalystsTab() {
  const [reviews, setReviews] = useState<CatalystReview[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const [statusFilter, setStatusFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchCatalysts = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceCatalysts(limit, offset);
      setReviews(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load catalyst reviews");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCatalysts();
  }, [offset]);

  const filteredItems = reviews.filter((item) => {
    if (statusFilter !== "all" && item.status !== statusFilter) return false;
    return true;
  });

  const { items: sortedItems, requestSort, sortConfig } = useSortableData(filteredItems, {
    key: "created_at",
    direction: "desc",
  });

  const currentSortKey = sortConfig?.key || "";
  const currentDirection = sortConfig?.direction || "desc";

  return (
    <Panel title="Missed Catalyst Audit">
      {error ? (
        <SectionError title="Failed to load catalyst reviews" message={error} retry={fetchCatalysts} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border border-zinc-800/40 bg-zinc-950/20 p-4 rounded-lg">
            <div className="text-sm text-zinc-400">
              Audit asset price moves that did not generate a corresponding market alert.
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-zinc-500">Status:</span>
              <div className="btn-group border border-zinc-800 rounded-lg p-0.5 bg-zinc-900 flex overflow-hidden">
                {["all", "pending", "investigating", "completed"].map((status) => (
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
            <EmptyState icon={Sparkles} title="No missed catalysts" body="Everything clean! No missed catalyst events to display." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th></th>
                    <SortableHeader label="Symbol" currentSortKey={currentSortKey} direction={currentDirection} sortKey="asset_symbol" onSort={requestSort} />
                    <SortableHeader label="Class" currentSortKey={currentSortKey} direction={currentDirection} sortKey="asset_class" onSort={requestSort} />
                    <SortableHeader label="Move Window" currentSortKey={currentSortKey} direction={currentDirection} sortKey="move_window" onSort={requestSort} />
                    <SortableHeader label="Price Change" currentSortKey={currentSortKey} direction={currentDirection} sortKey="price_change_pct" onSort={requestSort} />
                    <SortableHeader label="Volume Change" currentSortKey={currentSortKey} direction={currentDirection} sortKey="volume_change_pct" onSort={requestSort} />
                    <SortableHeader label="Status" currentSortKey={currentSortKey} direction={currentDirection} sortKey="status" onSort={requestSort} />
                    <SortableHeader label="Detected Event" currentSortKey={currentSortKey} direction={currentDirection} sortKey="detected_event_cluster_id" onSort={requestSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {sortedItems.map((row) => {
                    const isExpanded = expandedId === row.id;
                    const isPositive = row.price_change_pct >= 0;
                    return (
                      <React.Fragment key={row.id}>
                        <tr className="hover:bg-zinc-800/10 transition-colors">
                          <td>
                            <button
                              className="btn btn-ghost btn-xs text-zinc-400 hover:text-white"
                              onClick={() => setExpandedId(isExpanded ? null : row.id)}
                              type="button"
                            >
                              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                          </td>
                          <td className="font-bold text-zinc-100">{row.asset_symbol}</td>
                          <td>
                            <Badge tone="neutral">
                              {row.asset_class}
                            </Badge>
                          </td>
                          <td className="font-semibold text-zinc-300">{row.move_window}</td>
                          <td className={`font-mono text-sm font-semibold ${isPositive ? "text-emerald-400" : "text-rose-400"}`}>
                            {isPositive ? "+" : ""}
                            {row.price_change_pct.toFixed(2)}%
                          </td>
                          <td className="font-mono text-xs">
                            {row.volume_change_pct != null ? `${row.volume_change_pct.toFixed(1)}%` : "—"}
                          </td>
                          <td>
                            <Badge
                              tone={
                                row.status === "completed"
                                  ? "success"
                                  : row.status === "investigating"
                                  ? "info"
                                  : "warning"
                              }
                            >
                              {row.status}
                            </Badge>
                          </td>
                          <td className="font-mono text-xs text-zinc-500">
                            {row.detected_event_cluster_id || "None"}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-zinc-950/30">
                            <td colSpan={8} className="p-4 border-l-2 border-indigo-500">
                              <div className="space-y-2">
                                <div className="text-xs uppercase tracking-wider text-zinc-500 font-bold">
                                  Agent Analysis Summary
                                </div>
                                <div className="text-sm bg-zinc-900 border border-zinc-800 p-3 rounded-lg text-zinc-300 leading-relaxed font-serif italic whitespace-pre-wrap">
                                  {row.agent_summary || "No agent analysis summary has been populated yet for this catalyst event."}
                                </div>
                                <div className="text-xs text-zinc-500 pt-1">
                                  Detected at: {new Date(row.created_at).toLocaleString()}
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
              <span className="font-semibold text-zinc-300">{total}</span> missed catalyst reviews
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
   TAB 4: EMBEDDINGS STATUS
   ========================================== */
