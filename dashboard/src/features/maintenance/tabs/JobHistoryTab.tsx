import { Activity, ChevronRight, RefreshCcw } from "lucide-react";

import type { JobRun } from "../../../api";
import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/EmptyState";
import { Panel } from "../../../components/Panel";
import { SectionError } from "../../../components/SectionError";
import { SortControls } from "../../../components/SortControls";
import { useSortableData } from "../../../hooks/useSortableData";
import { formatTime } from "../../../lib/time";

export function JobHistoryTab({
  rows,
  error,
  retry,
}: {
  rows: JobRun[];
  error?: string;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "started_at",
    direction: "desc",
  });

  return (
    <Panel className="w-full max-w-4xl" title="Job history">
      {error ? (
        <SectionError title="Job history unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Activity}
          title="No job runs yet"
          body="Pipeline and maintenance job runs will appear after the bot records activity."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between border-b border-zinc-800/40 pb-2 text-xs text-zinc-500">
            <span>Job Name</span>
            <SortControls
              currentSortKey={sortConfig.key}
              direction={sortConfig.direction}
              label="Sort by:"
              onSort={requestSort}
              options={[
                { key: "job_name", label: "Name" },
                { key: "status", label: "Status" },
                { key: "started_at", label: "Time" },
              ]}
            />
          </div>
          <div className="space-y-2.5">
            {sortedRows.map((row) => (
              <div
                key={row.id}
                className="flex items-center justify-between gap-3 border-b border-zinc-800/30 py-1 text-sm last:border-0"
              >
                <div className="flex flex-col">
                  <span className="font-semibold text-zinc-200">{row.job_name}</span>
                  {row.started_at ? (
                    <span className="mt-0.5 text-[10px] text-zinc-500">
                      {formatTime(row.started_at)}
                    </span>
                  ) : null}
                </div>
                <span className="flex items-center gap-2">
                  <Badge tone={row.status === "success" ? "success" : "error"}>{row.status}</Badge>
                  <ChevronRight className="h-4 w-4 text-base-content/50" />
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
