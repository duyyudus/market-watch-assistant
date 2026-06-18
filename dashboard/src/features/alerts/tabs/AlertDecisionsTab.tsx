import { ChevronLeft, ChevronRight, RefreshCcw } from "lucide-react";

import type { AlertDecision, EventDetail } from "../../../api";
import { Panel } from "../../../components/Panel";
import { AlertsTable } from "../AlertsTable";
import { AlertDetailPanel } from "./AlertDetailPanel";

const DECISION_FILTERS = [
  { label: "All", value: null },
  { label: "Immediate", value: "immediate_alert" },
  { label: "Watchlist", value: "watchlist_batch" },
  { label: "Digest", value: "daily_digest" },
  { label: "Archive", value: "archive_only" },
] satisfies Array<{ label: string; value: string | null }>;

export function AlertDecisionsTab({
  alerts,
  error,
  maxItems,
  decision,
  offset,
  pageSize,
  total,
  setMaxItems,
  setDecision,
  setOffset,
  selectedAlertId,
  selectedAlertDetail,
  selectedAlertEventDetail,
  alertError,
  eventError,
  retry,
  retryDetail,
  onSelectAlert,
}: {
  alerts: AlertDecision[];
  error?: string;
  maxItems: number | null;
  decision: string | null;
  offset: number;
  pageSize: number;
  total: number;
  setMaxItems: (value: number | null) => void;
  setDecision: (value: string | null) => void;
  setOffset: (value: number) => void;
  selectedAlertId?: string;
  selectedAlertDetail?: AlertDecision;
  selectedAlertEventDetail?: EventDetail;
  alertError?: string;
  eventError?: string;
  retry: () => Promise<void>;
  retryDetail: () => Promise<void>;
  onSelectAlert: (id: string) => void;
}) {
  const pageStart = total > 0 ? Math.min(offset + 1, total) : 0;
  const pageEnd = Math.min(offset + pageSize, total);
  const canGoPrevious = offset > 0;
  const canGoNext = offset + pageSize < total;

  return (
    <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
      <Panel title="Alert decisions">
        <div className="mb-4 grid gap-3 lg:grid-cols-[150px_minmax(280px,1fr)_auto] lg:items-end">
          <label className="form-control w-full">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Max items</span>
            </span>
            <select
              aria-label="Alert max items"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) =>
                setMaxItems(event.target.value === "all" ? null : Number(event.target.value))
              }
              value={maxItems ?? "all"}
            >
              {[100, 250, 500, 1000].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
              <option value="all">All</option>
            </select>
          </label>
          <div className="form-control w-full">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Decision</span>
            </span>
            <div className="join flex flex-wrap">
              {DECISION_FILTERS.map((filter) => (
                <button
                  className={`btn join-item btn-sm ${
                    decision === filter.value ? "btn-primary" : "btn-outline"
                  }`}
                  key={filter.label}
                  onClick={() => setDecision(filter.value)}
                  type="button"
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
          <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        </div>
        <AlertsTable
          rows={alerts}
          error={error}
          retry={retry}
          selectedAlertId={selectedAlertId}
          onSelectAlert={onSelectAlert}
          showDecisionColumn={false}
        />
        {!error ? (
          <div className="mt-4 flex flex-col gap-2 border-t border-zinc-800/60 pt-3 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
            <span>
              {pageStart}-{pageEnd} of {total}
            </span>
            <div className="join">
              <button
                aria-label="Previous alert page"
                className="btn join-item btn-sm btn-outline"
                disabled={!canGoPrevious}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                type="button"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                aria-label="Next alert page"
                className="btn join-item btn-sm btn-outline"
                disabled={!canGoNext}
                onClick={() => setOffset(offset + pageSize)}
                type="button"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        ) : null}
      </Panel>
      <div className="xl:sticky xl:top-20 xl:self-start xl:max-h-[calc(100vh-100px)] xl:overflow-y-auto xl:overflow-x-hidden">
        <Panel title="Alert detail">
          <AlertDetailPanel
            alert={selectedAlertDetail}
            eventDetail={selectedAlertEventDetail}
            alertError={alertError}
            eventError={eventError}
            retry={retryDetail}
          />
        </Panel>
      </div>
    </div>
  );
}
