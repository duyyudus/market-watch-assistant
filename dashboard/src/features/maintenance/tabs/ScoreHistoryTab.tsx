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

export function ScoreHistoryTab() {
  const [history, setHistory] = useState<ScoreHistory[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const [eventIdFilter, setEventIdFilter] = useState("");
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  const fetchScoreHistory = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceScoreHistory(limit, offset);
      setHistory(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err?.message || "Failed to load score history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScoreHistory();
  }, [offset]);

  const filteredItems = history.filter((item) => {
    if (eventIdFilter && !item.event_cluster_id.toLowerCase().includes(eventIdFilter.toLowerCase()))
      return false;
    return true;
  });

  const { items: sortedItems, requestSort, sortConfig } = useSortableData(filteredItems, {
    key: "created_at",
    direction: "desc",
  });

  const currentSortKey = sortConfig?.key || "";
  const currentDirection = sortConfig?.direction || "desc";

  return (
    <Panel title="Event Score Timeline">
      {error ? (
        <SectionError title="Failed to load score history" message={error} retry={fetchScoreHistory} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border border-zinc-800/40 bg-zinc-950/20 p-4 rounded-lg">
            <div className="text-sm text-zinc-400">
              Audit the progression of scoring criteria across events over time.
            </div>
            <div className="relative w-full sm:max-w-xs">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
              <input
                className="input input-sm input-bordered pl-9 w-full bg-zinc-950/40 border-zinc-800 text-zinc-200 placeholder-zinc-500"
                onChange={(e) => setEventIdFilter(e.target.value)}
                placeholder="Search Event ID..."
                type="text"
                value={eventIdFilter}
              />
            </div>
          </div>

          {loading ? (
            <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>
          ) : sortedItems.length === 0 ? (
            <EmptyState icon={Sliders} title="No score history" body="No scores found." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th></th>
                    <SortableHeader label="Score ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="id" onSort={requestSort} />
                    <SortableHeader label="Event Cluster ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="event_cluster_id" onSort={requestSort} />
                    <SortableHeader label="Final Score" currentSortKey={currentSortKey} direction={currentDirection} sortKey="final_score" onSort={requestSort} />
                    <SortableHeader label="Evaluation Time" currentSortKey={currentSortKey} direction={currentDirection} sortKey="created_at" onSort={requestSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {sortedItems.map((score) => {
                    const isExpanded = expandedRowId === score.id;
                    return (
                      <React.Fragment key={score.id}>
                        <tr className="hover:bg-zinc-800/10 transition-colors">
                          <td>
                            <button
                              className="btn btn-ghost btn-xs text-zinc-400 hover:text-white"
                              onClick={() => setExpandedRowId(isExpanded ? null : score.id)}
                              type="button"
                            >
                              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                          </td>
                          <td className="font-mono text-xs text-zinc-500">{score.id}</td>
                          <td className="font-mono text-xs text-zinc-300">{score.event_cluster_id}</td>
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-sm text-zinc-100">{score.final_score}</span>
                              <div className="w-16 bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className={`h-1.5 rounded-full ${
                                    score.final_score >= 80 ? "bg-emerald-500" : score.final_score >= 50 ? "bg-amber-500" : "bg-rose-500"
                                  }`}
                                  style={{ width: `${Math.min(100, score.final_score)}%` }}
                                ></div>
                              </div>
                            </div>
                          </td>
                          <td className="text-zinc-400 text-xs">
                            {new Date(score.created_at).toLocaleString()}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-zinc-950/30">
                            <td colSpan={5} className="p-4 border-l-2 border-indigo-500">
                              <div>
                                <span className="text-xs uppercase tracking-wider text-zinc-500 block mb-2 font-bold">
                                  Score Breakdown
                                </span>
                                <div className="grid gap-2 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                                  {Object.entries(score.score_breakdown || {}).map(([key, value]) => (
                                    <div key={key} className="bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 flex justify-between items-center text-xs">
                                      <span className="text-zinc-400 font-semibold">{key}</span>
                                      <span className="font-mono text-indigo-400 bg-indigo-950/50 px-2 py-0.5 rounded border border-indigo-900/50 font-bold">
                                        {JSON.stringify(value)}
                                      </span>
                                    </div>
                                  ))}
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
              <span className="font-semibold text-zinc-300">{total}</span> total score audit logs
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
   TAB 3: CATALYST REVIEW
   ========================================== */
