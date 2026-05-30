import {
  AlertTriangle,
  Bell,
  ChevronDown,
  ChevronRight,
  Layers,
  Play,
  Radio,
  RefreshCcw,
  Search,
  ShieldAlert,
  TerminalSquare,
  Trash2,
  XCircle,
} from "lucide-react";
import { Fragment, useState } from "react";

import type { BotCommand, EventCluster, Source } from "../../api";
import { api } from "../../api";
import { Badge } from "../../components/Badge";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { formatTime } from "../../lib/time";
import type { QueueCommand } from "../../types/dashboard";

const EVENT_STATUSES = [
  "reported",
  "confirmed",
  "official",
  "stale",
  "false_signal",
  "merged",
] as const;

const STATUS_TONE: Record<string, "info" | "warning" | "success" | "error"> = {
  pending: "info",
  running: "warning",
  succeeded: "success",
  failed: "error",
  cancelled: "info",
};

type PendingConfirm = {
  title: string;
  description: string;
  commandType: string;
  payload: Record<string, unknown>;
};

export function CommandsTable({
  rows,
  compact = false,
  error,
  retry,
  queue,
  queueUnavailable = false,
  sources = [],
  events = [],
}: {
  rows: BotCommand[];
  compact?: boolean;
  error?: string;
  retry: () => Promise<void>;
  queue: QueueCommand;
  queueUnavailable?: boolean;
  sources?: Source[];
  events?: EventCluster[];
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "created_at",
    direction: "desc",
  });

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [eventSelectCmd, setEventSelectCmd] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState("");
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [markStatus, setMarkStatus] = useState<string>("confirmed");

  function confirmThenQueue(pending: PendingConfirm) {
    setConfirm(pending);
  }

  async function handleConfirm() {
    if (!confirm) return;
    await queue(confirm.commandType, confirm.payload);
    setConfirm(null);
  }

  async function handleCancel(commandId: string) {
    await api.cancelCommand(commandId);
    await retry();
  }

  if (error) {
    return <SectionError title="Command queue unavailable" message={error} retry={retry} />;
  }

  const migrationNotice = queueUnavailable ? (
    <div className="alert alert-warning text-sm mb-3">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <div>
        <p className="font-semibold">Command queue unavailable</p>
        <p className="mt-0.5 text-xs opacity-80">
          Run the migration first:{" "}
          <code className="bg-zinc-800 px-1.5 py-0.5 rounded text-xs">
            cd market-watch-bot &amp;&amp; uv run market-watch migrate
          </code>
        </p>
      </div>
    </div>
  ) : null;

  const commandCenter = !compact ? (
    <div className="space-y-3 mb-4">
      {migrationNotice}

      {/* Pipeline commands */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Pipeline
        </span>
        <button
          className="btn btn-sm btn-outline btn-warning"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Run live pipeline?",
              description:
                "This will run the full pipeline with real ingestion, clustering, scoring, and alert decisions. No dry-run protection.",
              commandType: "pipeline.run",
              payload: { dry_run: false },
            })
          }
          type="button"
        >
          <Play className="h-3.5 w-3.5" />
          Live run
        </button>
      </div>

      {/* Alert dispatch */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Alerts
        </span>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() =>
            queue("alert.dispatch", { channel: "telegram", limit: 20, dry_run: true })
          }
          type="button"
        >
          <Bell className="h-3.5 w-3.5" />
          Preview dispatch
        </button>
        <button
          className="btn btn-sm btn-outline btn-warning"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Send live alerts?",
              description:
                "This will dispatch real Telegram alerts for pending alert decisions. This action cannot be undone.",
              commandType: "alert.dispatch",
              payload: { channel: "telegram", limit: 20, dry_run: false },
            })
          }
          type="button"
        >
          <Bell className="h-3.5 w-3.5" />
          Send alerts
        </button>
      </div>

      {/* Event commands */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Events
        </span>
        {events.length > 0 ? (
          <>
            <select
              className="select select-bordered select-sm max-w-[220px] text-xs"
              value={selectedEventId}
              onChange={(e) => setSelectedEventId(e.target.value)}
              aria-label="Select event"
            >
              <option value="">Select event…</option>
              {events.slice(0, 50).map((event) => (
                <option key={event.id} value={event.id}>
                  {event.canonical_headline.slice(0, 60)}
                </option>
              ))}
            </select>
            <button
              className="btn btn-sm btn-outline"
              disabled={queueUnavailable || !selectedEventId}
              onClick={() => queue("event.rescore", { event_id: selectedEventId })}
              type="button"
            >
              Rescore
            </button>
            <button
              className="btn btn-sm btn-outline"
              disabled={queueUnavailable || !selectedEventId}
              onClick={() =>
                queue("investigation.run_event", { event_id: selectedEventId })
              }
              type="button"
            >
              <Search className="h-3.5 w-3.5" />
              Investigate
            </button>
            <div className="flex items-center gap-1">
              <select
                className="select select-bordered select-sm text-xs w-32"
                value={markStatus}
                onChange={(e) => setMarkStatus(e.target.value)}
                aria-label="Mark status"
              >
                {EVENT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <button
                className="btn btn-sm btn-outline btn-warning"
                disabled={queueUnavailable || !selectedEventId}
                onClick={() =>
                  confirmThenQueue({
                    title: `Mark event as "${markStatus}"?`,
                    description: `This will change the event status to "${markStatus}". The original status can be restored with another mark command.`,
                    commandType: "event.mark",
                    payload: { event_id: selectedEventId, status: markStatus },
                  })
                }
                type="button"
              >
                Mark
              </button>
            </div>
          </>
        ) : (
          <span className="text-xs text-zinc-500">No events loaded</span>
        )}
      </div>

      {/* Recluster */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Cluster
        </span>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() => queue("event.recluster", { since: "48h", limit: 500, apply: false })}
          type="button"
        >
          <Layers className="h-3.5 w-3.5" />
          Preview recluster
        </button>
        <button
          className="btn btn-sm btn-outline btn-warning"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Apply recluster?",
              description:
                "This will re-run event clustering and apply the changes to the database. Preview first to check the impact.",
              commandType: "event.recluster",
              payload: { since: "48h", limit: 500, apply: true },
            })
          }
          type="button"
        >
          <Layers className="h-3.5 w-3.5" />
          Apply recluster
        </button>
      </div>

      {/* Source fetch */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Sources
        </span>
        {sources.length > 0 ? (
          <>
            <select
              className="select select-bordered select-sm max-w-[220px] text-xs"
              value={selectedSourceId}
              onChange={(e) => setSelectedSourceId(e.target.value)}
              aria-label="Select source"
            >
              <option value="">Select source…</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
            <button
              className="btn btn-sm btn-outline"
              disabled={queueUnavailable || !selectedSourceId}
              onClick={() => queue("source.fetch", { source_id: selectedSourceId })}
              type="button"
            >
              <Radio className="h-3.5 w-3.5" />
              Fetch
            </button>
          </>
        ) : (
          <span className="text-xs text-zinc-500">No sources loaded</span>
        )}
      </div>

      {/* Retention */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Retention
        </span>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() => queue("retention.preview", {})}
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Preview
        </button>
        <button
          className="btn btn-sm btn-outline btn-error"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Run retention cleanup?",
              description:
                "This will permanently delete expired data according to retention policy. Run a preview first to see what will be removed. This action cannot be undone.",
              commandType: "retention.run",
              payload: {},
            })
          }
          type="button"
        >
          <ShieldAlert className="h-3.5 w-3.5" />
          Run retention
        </button>
      </div>
    </div>
  ) : compact && migrationNotice ? (
    migrationNotice
  ) : null;

  return (
    <div className="space-y-3">
      {commandCenter}

      {sortedRows.length === 0 ? (
        <EmptyState
          icon={TerminalSquare}
          title="No commands queued"
          body="Manual bot commands will appear here after an operator queues one."
          action={
            compact ? null : (
              <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </button>
            )
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="table w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                {!compact ? <th className="w-8" /> : null}
                <SortableHeader
                  label="Command"
                  sortKey="command_type"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Status"
                  sortKey="status"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Created"
                  sortKey="created_at"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                {!compact ? (
                  <>
                    <th className="py-3 px-4 text-left">Payload</th>
                    <th className="py-3 px-4 text-left">Actions</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => {
                const isExpanded = expandedId === row.id;
                return (
                  <Fragment key={row.id}>
                    <tr className="border-b border-zinc-800/30">
                      {!compact ? (
                        <td className="py-3 px-2">
                          <button
                            className="btn btn-ghost btn-xs btn-square"
                            onClick={() => setExpandedId(isExpanded ? null : row.id)}
                            type="button"
                            aria-label={`Toggle details for ${row.id}`}
                          >
                            {isExpanded ? (
                              <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                              <ChevronRight className="h-3.5 w-3.5" />
                            )}
                          </button>
                        </td>
                      ) : null}
                      <td className="py-3 px-4 text-sm font-semibold text-zinc-200">
                        {row.command_type}
                      </td>
                      <td className="py-3 px-4 text-xs">
                        <Badge tone={STATUS_TONE[row.status] ?? "info"}>{row.status}</Badge>
                      </td>
                      <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                        {formatTime(row.created_at)}
                      </td>
                      {!compact ? (
                        <>
                          <td className="py-3 px-4 text-zinc-400 font-normal text-xs max-w-[280px] truncate">
                            {JSON.stringify(row.payload)}
                          </td>
                          <td className="py-3 px-4">
                            {row.status === "pending" ? (
                              <button
                                className="btn btn-ghost btn-xs text-error"
                                onClick={() => void handleCancel(row.id)}
                                type="button"
                                aria-label={`Cancel ${row.command_type}`}
                              >
                                <XCircle className="h-3.5 w-3.5" />
                                Cancel
                              </button>
                            ) : null}
                          </td>
                        </>
                      ) : null}
                    </tr>
                    {isExpanded && !compact ? (
                      <tr className="bg-zinc-900/50">
                        <td colSpan={6} className="px-8 py-3">
                          <div className="grid gap-2 text-xs">
                            <div className="flex gap-6">
                              <span className="text-zinc-500">ID:</span>
                              <span className="font-mono text-zinc-300">{row.id}</span>
                            </div>
                            {row.started_at ? (
                              <div className="flex gap-6">
                                <span className="text-zinc-500">Started:</span>
                                <span className="text-zinc-300">{formatTime(row.started_at)}</span>
                              </div>
                            ) : null}
                            {row.completed_at ? (
                              <div className="flex gap-6">
                                <span className="text-zinc-500">Completed:</span>
                                <span className="text-zinc-300">
                                  {formatTime(row.completed_at)}
                                </span>
                              </div>
                            ) : null}
                            {row.result ? (
                              <div>
                                <span className="text-zinc-500">Result:</span>
                                <pre className="mt-1 max-h-40 overflow-auto rounded bg-zinc-800 p-2 text-zinc-300 font-mono text-xs">
                                  {JSON.stringify(row.result, null, 2)}
                                </pre>
                              </div>
                            ) : null}
                            {row.error_message ? (
                              <div>
                                <span className="text-zinc-500">Error:</span>
                                <pre className="mt-1 max-h-40 overflow-auto rounded bg-red-950/40 border border-red-900/40 p-2 text-red-300 font-mono text-xs">
                                  {row.error_message}
                                </pre>
                              </div>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.title ?? ""}
        description={confirm?.description ?? ""}
        confirmLabel="Execute"
        confirmTone="btn-warning"
        onConfirm={() => void handleConfirm()}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
