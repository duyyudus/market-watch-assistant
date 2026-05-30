import { Activity, ChevronRight, RefreshCcw } from "lucide-react";

import type { JobRun } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { formatTime } from "../../lib/time";

export function JobsTable({
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

  if (error) {
    return <SectionError title="Job history unavailable" message={error} retry={retry} />;
  }

  if (sortedRows.length === 0) {
    return (
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
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-zinc-800/40 pb-2 text-xs text-zinc-500">
        <span>Job Name</span>
        <div className="flex items-center gap-3">
          <button
            onClick={() => requestSort("job_name")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "job_name" && "text-primary font-semibold",
            )}
            type="button"
          >
            Name
            {sortConfig.key === "job_name" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("status")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "status" && "text-primary font-semibold",
            )}
            type="button"
          >
            Status
            {sortConfig.key === "status" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
          <button
            onClick={() => requestSort("started_at")}
            className={classNames(
              "hover:text-primary transition-colors flex items-center gap-0.5",
              sortConfig.key === "started_at" && "text-primary font-semibold",
            )}
            type="button"
          >
            Time
            {sortConfig.key === "started_at" && (sortConfig.direction === "asc" ? " ▲" : " ▼")}
          </button>
        </div>
      </div>
      <div className="space-y-2.5">
        {sortedRows.map((row) => (
          <div
            key={row.id}
            className="flex items-center justify-between gap-3 text-sm py-1 border-b border-zinc-800/30 last:border-0"
          >
            <div className="flex flex-col">
              <span className="font-semibold text-zinc-200">{row.job_name}</span>
              {row.started_at ? (
                <span className="text-[10px] text-zinc-500 mt-0.5">
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
  );
}

