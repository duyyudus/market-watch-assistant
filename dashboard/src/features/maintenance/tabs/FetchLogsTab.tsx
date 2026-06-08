import React, { useEffect, useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronUp,
  Search,
} from "lucide-react";

import { api } from "../../../api";
import type { FetchLog } from "../../../api";
import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/EmptyState";
import { Panel } from "../../../components/Panel";
import { SectionError } from "../../../components/SectionError";
import { SortableHeader } from "../../../components/SortableHeader";
import { useSortableData } from "../../../hooks/useSortableData";

export function FetchLogsTab() {
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
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load fetch logs");
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
