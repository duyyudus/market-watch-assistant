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

export function RetentionTab() {
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
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load retention jobs history");
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
