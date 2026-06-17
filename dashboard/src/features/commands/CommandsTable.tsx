import {
  AlertTriangle,
  Bell,
  Layers,
  Play,
  Radio,
  RefreshCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import type { BotCommand, EventCluster, Source } from "../../api";
import { api } from "../../api";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SectionError } from "../../components/SectionError";
import { useSortableData } from "../../hooks/useSortableData";
import type { QueueCommand } from "../../types/dashboard";
import { CommandHistoryTable } from "./CommandHistoryTable";

const EVENT_STATUSES = [
  "reported",
  "confirmed",
  "official",
  "stale",
  "false_signal",
  "merged",
] as const;

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
  const [selectedEventId, setSelectedEventId] = useState("");
  const [targetEventId, setTargetEventId] = useState("");
  const [splitNewsIds, setSplitNewsIds] = useState("");
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

      {/* Digest */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Digest
        </span>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() => queue("digest.send", { hours: 24, dry_run: true })}
          type="button"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Build digest
        </button>
        <button
          className="btn btn-sm btn-outline btn-warning"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Send daily digest?",
              description:
                "This builds the last 24h digest and dispatches it to Telegram. This action cannot be undone.",
              commandType: "digest.send",
              payload: { hours: 24, dry_run: false },
            })
          }
          type="button"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Send digest
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
            <select
              className="select select-bordered select-sm max-w-[220px] text-xs"
              value={targetEventId}
              onChange={(e) => setTargetEventId(e.target.value)}
              aria-label="Select merge target event"
            >
              <option value="">Merge target…</option>
              {events
                .filter((event) => event.id !== selectedEventId)
                .slice(0, 50)
                .map((event) => (
                  <option key={event.id} value={event.id}>
                    {event.canonical_headline.slice(0, 60)}
                  </option>
                ))}
            </select>
            <button
              className="btn btn-sm btn-outline btn-warning"
              disabled={queueUnavailable || !selectedEventId || !targetEventId}
              onClick={() =>
                confirmThenQueue({
                  title: "Merge event clusters?",
                  description:
                    "This will move all source event news items into the target event and mark the source event as merged.",
                  commandType: "event.merge",
                  payload: {
                    source_event_id: selectedEventId,
                    target_event_id: targetEventId,
                  },
                })
              }
              type="button"
            >
              Merge
            </button>
            <input
              className="input input-bordered input-sm max-w-[240px] text-xs"
              value={splitNewsIds}
              onChange={(e) => setSplitNewsIds(e.target.value)}
              placeholder="news_1,news_2"
              aria-label="Split news item IDs"
            />
            <button
              className="btn btn-sm btn-outline btn-warning"
              disabled={queueUnavailable || !selectedEventId || !splitNewsIds.trim()}
              onClick={() =>
                confirmThenQueue({
                  title: "Split event cluster?",
                  description:
                    "This will move the listed news items into a new event cluster and rescore both clusters.",
                  commandType: "event.split",
                  payload: {
                    event_id: selectedEventId,
                    news_item_ids: splitNewsIds
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  },
                })
              }
              type="button"
            >
              Split
            </button>
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

      {/* Data quality */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 w-20">
          Quality
        </span>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() => queue("source.quality.refresh", {})}
          type="button"
        >
          <RefreshCcw className="h-3.5 w-3.5" />
          Refresh quality
        </button>
        <button
          className="btn btn-sm btn-outline"
          disabled={queueUnavailable}
          onClick={() =>
            queue("event.compact_archived", {
              older_than: "30d",
              limit: 500,
              apply: false,
            })
          }
          type="button"
        >
          <Layers className="h-3.5 w-3.5" />
          Preview compaction
        </button>
        <button
          className="btn btn-sm btn-outline btn-warning"
          disabled={queueUnavailable}
          onClick={() =>
            confirmThenQueue({
              title: "Compact archived events?",
              description:
                "This will store compact summaries for old archive-only events and remove their embeddings.",
              commandType: "event.compact_archived",
              payload: { older_than: "30d", limit: 500, apply: true },
            })
          }
          type="button"
        >
          <Layers className="h-3.5 w-3.5" />
          Compact archived
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

      <CommandHistoryTable
        rows={sortedRows}
        compact={compact}
        expandedId={expandedId}
        sortKey={sortConfig.key}
        sortDirection={sortConfig.direction}
        onExpand={setExpandedId}
        onSort={requestSort}
        onCancel={(commandId) => void handleCancel(commandId)}
        retry={retry}
      />

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
