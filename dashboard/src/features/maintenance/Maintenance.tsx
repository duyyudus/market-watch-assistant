import React, { useEffect, useState } from "react";
import {
  Activity,
  Brain,
  Database,
  History,
  Layers,
  Search,
  Sliders,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import { api } from "../../api";
import type {
  FetchLog,
  ScoreHistory,
  CatalystReview,
  EmbeddingStats,
  LLMRun,
  RetentionJob,
} from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";

type Tab = "fetch-logs" | "score-history" | "catalysts" | "embeddings" | "llm-runs" | "retention";

export function Maintenance() {
  const [activeTab, setActiveTab] = useState<Tab>("fetch-logs");

  return (
    <div className="space-y-6">

      {/* Tabs navigation */}
      <div className="tabs tabs-boxed border border-zinc-800/60 bg-zinc-950/60 p-1 flex flex-wrap gap-1">
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "fetch-logs" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("fetch-logs")}
          type="button"
        >
          <Activity className="h-3.5 w-3.5" />
          Fetch Logs
        </button>
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "score-history" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("score-history")}
          type="button"
        >
          <Sliders className="h-3.5 w-3.5" />
          Score History
        </button>
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "catalysts" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("catalysts")}
          type="button"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Catalysts
        </button>
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "embeddings" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("embeddings")}
          type="button"
        >
          <Layers className="h-3.5 w-3.5" />
          Embeddings Coverage
        </button>
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "llm-runs" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("llm-runs")}
          type="button"
        >
          <Brain className="h-3.5 w-3.5" />
          LLM Diagnostics
        </button>
        <button
          className={`tab tab-sm sm:tab-md transition-all duration-200 flex items-center gap-2 ${
            activeTab === "retention" ? "tab-active bg-indigo-600/90 text-white font-bold" : "text-zinc-400 hover:text-zinc-200"
          }`}
          onClick={() => setActiveTab("retention")}
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
          Retention Logs
        </button>
      </div>

      {/* Tab Panel */}
      <div className="transition-all duration-300">
        {activeTab === "fetch-logs" && <FetchLogsTab />}
        {activeTab === "score-history" && <ScoreHistoryTab />}
        {activeTab === "catalysts" && <CatalystsTab />}
        {activeTab === "embeddings" && <EmbeddingsTab />}
        {activeTab === "llm-runs" && <LLMRunsTab />}
        {activeTab === "retention" && <RetentionTab />}
      </div>
    </div>
  );
}

// Custom hook to represent trash icon to satisfy TypeScript compiler
function Trash2({ className, strokeWidth }: { className?: string; strokeWidth?: number }) {
  return <TrashIcon className={className} strokeWidth={strokeWidth} />;
}

import { Trash as TrashIcon } from "lucide-react";

/* ==========================================
   TAB 1: FETCH LOGS
   ========================================== */
function FetchLogsTab() {
  const [logs, setLogs] = useState<FetchLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  // Filter states
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("");

  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceFetchLogs(limit, offset);
      setLogs(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err?.message || "Failed to load fetch logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [offset]);

  const filteredItems = logs.filter((log) => {
    if (statusFilter !== "all" && log.status !== statusFilter) return false;
    if (
      sourceFilter &&
      !log.source_id.toLowerCase().includes(sourceFilter.toLowerCase())
    )
      return false;
    return true;
  });

  const { items: sortedItems, requestSort, sortConfig } = useSortableData(filteredItems, {
    key: "fetched_at",
    direction: "desc",
  });

  const currentSortKey = sortConfig?.key || "";
  const currentDirection = sortConfig?.direction || "desc";

  return (
    <Panel title="Source Fetch Logs">
      {error ? (
        <SectionError title="Failed to load fetch logs" message={error} retry={fetchLogs} />
      ) : (
        <div className="space-y-4">
          {/* Filters Panel */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border border-zinc-800/40 bg-zinc-950/20 p-4 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-zinc-500">Status:</span>
              <div className="btn-group border border-zinc-800 rounded-lg p-0.5 bg-zinc-900 flex overflow-hidden">
                {["all", "success", "error"].map((status) => (
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

            <div className="relative w-full sm:max-w-xs">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
              <input
                className="input input-sm input-bordered pl-9 w-full bg-zinc-950/40 border-zinc-800 text-zinc-200 placeholder-zinc-500"
                onChange={(e) => setSourceFilter(e.target.value)}
                placeholder="Filter by Source ID..."
                type="text"
                value={sourceFilter}
              />
            </div>
          </div>

          {loading ? (
            <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>
          ) : sortedItems.length === 0 ? (
            <EmptyState icon={Activity} title="No logs found" body="No fetch operations match your filters." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th></th>
                    <SortableHeader label="Log ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="id" onSort={requestSort} />
                    <SortableHeader label="Source ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="source_id" onSort={requestSort} />
                    <SortableHeader label="Time" currentSortKey={currentSortKey} direction={currentDirection} sortKey="fetched_at" onSort={requestSort} />
                    <SortableHeader label="Status" currentSortKey={currentSortKey} direction={currentDirection} sortKey="status" onSort={requestSort} />
                    <SortableHeader label="HTTP" currentSortKey={currentSortKey} direction={currentDirection} sortKey="http_status" onSort={requestSort} />
                    <SortableHeader label="Items" currentSortKey={currentSortKey} direction={currentDirection} sortKey="item_count" onSort={requestSort} />
                    <SortableHeader label="Duration" currentSortKey={currentSortKey} direction={currentDirection} sortKey="duration_ms" onSort={requestSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {sortedItems.map((log) => {
                    const isExpanded = expandedLogId === log.id;
                    return (
                      <React.Fragment key={log.id}>
                        <tr className="hover:bg-zinc-800/10 transition-colors">
                          <td>
                            <button
                              className="btn btn-ghost btn-xs text-zinc-400 hover:text-white"
                              onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                              type="button"
                            >
                              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                          </td>
                          <td className="font-mono text-xs text-zinc-500">{log.id}</td>
                          <td className="font-medium text-zinc-300 max-w-[150px] truncate" title={log.source_id}>
                            {log.source_id}
                          </td>
                          <td className="text-zinc-400 text-xs">
                            {new Date(log.fetched_at).toLocaleString()}
                          </td>
                          <td>
                            {log.status === "success" ? (
                              <Badge tone="success">Success</Badge>
                            ) : (
                              <Badge tone="error">Error</Badge>
                            )}
                          </td>
                          <td className="font-mono text-xs">
                            {log.http_status ? (
                              <span className={log.http_status >= 400 ? "text-rose-400" : "text-emerald-400"}>
                                {log.http_status}
                              </span>
                            ) : (
                              <span className="text-zinc-600">—</span>
                            )}
                          </td>
                          <td className="font-semibold text-zinc-300">{log.item_count ?? 0}</td>
                          <td className="font-mono text-xs text-indigo-300">{log.duration_ms} ms</td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-zinc-950/30">
                            <td colSpan={8} className="p-4 border-l-2 border-indigo-500">
                              <div className="space-y-2.5 text-sm">
                                <div>
                                  <span className="text-xs uppercase tracking-wider text-zinc-500 block">Content Hash</span>
                                  <span className="font-mono text-xs text-zinc-400">{log.content_hash || "None"}</span>
                                </div>
                                {log.error_message && (
                                  <div>
                                    <span className="text-xs uppercase tracking-wider text-zinc-500 block">Error Message</span>
                                    <div className="mockup-code bg-zinc-900 border border-zinc-800 text-rose-400 text-xs mt-1 p-3 whitespace-pre-wrap max-h-48 overflow-y-auto">
                                      {log.error_message}
                                    </div>
                                  </div>
                                )}
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
              <span className="font-semibold text-zinc-300">{total}</span> total fetch operations
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
   TAB 2: EVENT SCORE HISTORY
   ========================================== */
function ScoreHistoryTab() {
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
function CatalystsTab() {
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
    } catch (err: any) {
      setError(err?.message || "Failed to load catalyst reviews");
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
function EmbeddingsTab() {
  const [stats, setStats] = useState<EmbeddingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceEmbeddingStats();
      setStats(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load embedding stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) {
    return (
      <Panel title="Vector Indexing Status">
        <div className="flex py-12 justify-center">
          <span className="loading loading-spinner loading-lg text-indigo-500" />
        </div>
      </Panel>
    );
  }

  if (error || !stats) {
    return (
      <Panel title="Vector Indexing Status">
        <SectionError title="Failed to load stats" message={error || "Empty response"} retry={fetchStats} />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      {/* Metrics Row */}
      <div className="grid gap-5 md:grid-cols-2">
        {/* Card 1 */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-zinc-500 font-bold">News Embedding Coverage</span>
            <Database className="h-4.5 w-4.5 text-indigo-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-zinc-100">{stats.news_items_with_embeddings}</span>
            <span className="text-zinc-500 text-sm">/ {stats.total_news_items} items</span>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-zinc-400 font-medium">Coverage Rate</span>
              <span className="font-bold text-indigo-400">{stats.embedding_coverage_pct.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden border border-zinc-800/80">
              <div
                className="bg-gradient-to-r from-indigo-500 to-violet-500 h-2 rounded-full"
                style={{ width: `${stats.embedding_coverage_pct}%` }}
              ></div>
            </div>
          </div>
        </div>

        {/* Card 2 */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-zinc-500 font-bold">Event Embedding Coverage</span>
            <Layers className="h-4.5 w-4.5 text-indigo-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-zinc-100">{stats.event_clusters_with_embeddings}</span>
            <span className="text-zinc-500 text-sm">/ {stats.total_event_clusters} clusters</span>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-zinc-400 font-medium">Coverage Rate</span>
              <span className="font-bold text-indigo-400">{stats.cluster_embedding_coverage_pct.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden border border-zinc-800/80">
              <div
                className="bg-gradient-to-r from-indigo-500 to-violet-500 h-2 rounded-full"
                style={{ width: `${stats.cluster_embedding_coverage_pct}%` }}
              ></div>
            </div>
          </div>
        </div>
      </div>

      {/* Details Lists */}
      <Panel title="Vector Model Specifications">
        <div className="grid gap-6 md:grid-cols-2">
          {/* News specs */}
          <div className="space-y-4">
            <h4 className="text-xs uppercase tracking-widest text-zinc-400 font-bold border-b border-zinc-800/60 pb-2">
              News Embedding Providers & Models
            </h4>
            <div className="space-y-3">
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Providers</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.news_providers.length > 0 ? (
                    stats.news_providers.map((p) => (
                      <Badge key={p} tone="neutral">{p}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No providers active</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Models</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.news_models.length > 0 ? (
                    stats.news_models.map((m) => (
                      <Badge key={m} tone="info">{m}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No models active</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Cluster specs */}
          <div className="space-y-4">
            <h4 className="text-xs uppercase tracking-widest text-zinc-400 font-bold border-b border-zinc-800/60 pb-2">
              Cluster Embedding Providers & Models
            </h4>
            <div className="space-y-3">
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Providers</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.cluster_providers.length > 0 ? (
                    stats.cluster_providers.map((p) => (
                      <Badge key={p} tone="neutral">{p}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No providers active</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Models</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.cluster_models.length > 0 ? (
                    stats.cluster_models.map((m) => (
                      <Badge key={m} tone="info">{m}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No models active</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/* ==========================================
   TAB 5: LLM DIAGNOSTICS & USAGE RUNS
   ========================================== */
function LLMRunsTab() {
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
   TAB 6: RETENTION HISTORY
   ========================================== */
function RetentionTab() {
  const [jobs, setJobs] = useState<RetentionJob[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchRetentionJobs = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceRetentionJobs(limit, offset);
      setJobs(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err?.message || "Failed to load retention jobs history");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRetentionJobs();
  }, [offset]);

  const { items: sortedItems, requestSort, sortConfig } = useSortableData(jobs, {
    key: "started_at",
    direction: "desc",
  });

  const currentSortKey = sortConfig?.key || "";
  const currentDirection = sortConfig?.direction || "desc";

  return (
    <Panel title="Database Retention Audits">
      {error ? (
        <SectionError title="Failed to load retention logs" message={error} retry={fetchRetentionJobs} />
      ) : (
        <div className="space-y-4">
          <div className="text-sm text-zinc-400 border border-zinc-800/40 bg-zinc-950/20 p-4 rounded-lg">
            Audit history of completed database pruning, event merging, and news item purging tasks.
          </div>

          {loading ? (
            <div className="flex py-12 justify-center"><span className="loading loading-spinner loading-lg text-indigo-500" /></div>
          ) : sortedItems.length === 0 ? (
            <EmptyState icon={History} title="No retention history" body="No retention prunings have run yet." />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th></th>
                    <SortableHeader label="Job ID" currentSortKey={currentSortKey} direction={currentDirection} sortKey="id" onSort={requestSort} />
                    <SortableHeader label="Status" currentSortKey={currentSortKey} direction={currentDirection} sortKey="status" onSort={requestSort} />
                    <SortableHeader label="Time Started" currentSortKey={currentSortKey} direction={currentDirection} sortKey="started_at" onSort={requestSort} />
                    <SortableHeader label="Time Completed" currentSortKey={currentSortKey} direction={currentDirection} sortKey="completed_at" onSort={requestSort} />
                    <SortableHeader label="Records Purged" currentSortKey={currentSortKey} direction={currentDirection} sortKey="deleted_counts" onSort={requestSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {sortedItems.map((job) => {
                    const isExpanded = expandedId === job.id;
                    const deletedList = Object.entries(job.deleted_counts || {});
                    const totalDeleted = deletedList.reduce((acc, [_, count]) => acc + count, 0);

                    return (
                      <React.Fragment key={job.id}>
                        <tr className="hover:bg-zinc-800/10 transition-colors">
                          <td>
                            <button
                              className="btn btn-ghost btn-xs text-zinc-400 hover:text-white"
                              onClick={() => setExpandedId(isExpanded ? null : job.id)}
                              type="button"
                            >
                              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                            </button>
                          </td>
                          <td className="font-mono text-xs text-zinc-500">{job.id}</td>
                          <td>
                            <Badge
                              tone={
                                job.status === "completed" || job.status === "succeeded"
                                  ? "success"
                                  : job.status === "failed"
                                  ? "error"
                                  : "warning"
                              }
                            >
                              {job.status}
                            </Badge>
                          </td>
                          <td className="text-zinc-400 text-xs">
                            {new Date(job.started_at).toLocaleString()}
                          </td>
                          <td className="text-zinc-400 text-xs">
                            {job.completed_at ? new Date(job.completed_at).toLocaleString() : "Running..."}
                          </td>
                          <td>
                            <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-200">
                              <span className="font-mono">{totalDeleted}</span>
                              <span className="text-zinc-500 font-normal">records</span>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-zinc-950/30">
                            <td colSpan={6} className="p-4 border-l-2 border-indigo-500">
                              <div>
                                <span className="text-xs uppercase tracking-wider text-zinc-500 block font-bold mb-2">
                                  Deleted Records Breakdown By Table
                                </span>
                                {deletedList.length === 0 ? (
                                  <span className="text-xs text-zinc-500 italic">No records were pruned.</span>
                                ) : (
                                  <div className="flex flex-wrap gap-2.5">
                                    {deletedList.map(([table, count]) => (
                                      <div
                                        key={table}
                                        className="bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 flex items-center gap-2 text-xs"
                                      >
                                        <span className="text-zinc-400 font-semibold">{table}:</span>
                                        <span className="font-mono text-rose-400 bg-rose-950/50 px-2 py-0.5 rounded border border-rose-900/50 font-bold">
                                          {count}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                )}
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
              <span className="font-semibold text-zinc-300">{total}</span> total retention job logs
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
