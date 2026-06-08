import { Radio, RefreshCcw } from "lucide-react";

import type { Source, SourceHealth } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import type { QueueCommand } from "../../types/dashboard";

export function SourceHealthPanel({
  health,
  sources,
  queue,
  reload,
  toggle,
}: {
  health: SourceHealth[];
  sources: Source[];
  queue: QueueCommand;
  reload: () => Promise<void>;
  toggle: (source: Source) => Promise<void>;
}) {
  if (!health.length) {
    return (
      <EmptyState
        icon={Radio}
        title="No source health yet"
        body="Fetch logs will appear after source polling runs."
        action={
          <button className="btn btn-sm btn-outline" onClick={() => void reload()} type="button">
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        }
      />
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {health.map((row) => {
        const source = sources.find((item) => item.id === row.source_id);
        return (
          <div className="rounded-md border border-zinc-800 bg-zinc-950/30 p-4" key={row.source_id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-sm font-bold text-zinc-100">{row.name}</div>
                <div className="mt-1 text-xs text-base-content/60">
                  {row.region} · {row.category} · {row.latest_status ?? "no fetch"}
                </div>
              </div>
              <span
                className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${healthStatusClass(
                  row.health_status,
                )}`}
              >
                {row.health_status}
              </span>
            </div>
            <div className="mt-3 grid gap-2 text-xs text-base-content/70 sm:grid-cols-3">
              <div>{row.average_latency_ms ?? "-"}ms avg</div>
              <div>{row.consecutive_failure_count} failures</div>
              <div>{row.enabled ? "enabled" : "disabled"}</div>
            </div>
            <div className="mt-3 flex h-12 items-end gap-1">
              {row.daily_item_counts.map((point) => (
                <div
                  className="w-4 rounded-t bg-primary/80 text-center text-[10px] text-base-100"
                  key={point.date}
                  style={{ height: `${Math.max(8, Math.min(48, point.count * 8))}px` }}
                  title={point.date}
                >
                  {point.count}
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                aria-label={`Test fetch ${row.name}`}
                className="btn btn-xs btn-outline btn-primary"
                onClick={() => queue("source.fetch", { source_id: row.source_id })}
                type="button"
              >
                Test fetch
              </button>
              {source ? (
                <button
                  className="btn btn-xs btn-outline btn-primary"
                  onClick={() => void toggle(source)}
                  type="button"
                >
                  {source.enabled ? "Disable" : "Enable"}
                </button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function healthStatusClass(status: SourceHealth["health_status"]): string {
  if (status === "healthy") {
    return "bg-emerald-500/10 text-emerald-400";
  }
  if (status === "degraded") {
    return "bg-amber-500/10 text-amber-400";
  }
  if (status === "disabled") {
    return "bg-zinc-700/30 text-zinc-400";
  }
  return "bg-red-500/10 text-red-400";
}
