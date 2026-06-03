import { Bell, Database } from "lucide-react";

import type { AlertDecision, EventDetail } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { SectionError } from "../../components/SectionError";
import { formatTime } from "../../lib/time";

function formatLabel(value: string) {
  return value.replace(/_/g, " ");
}

const decisionTones: Record<string, string> = {
  immediate_alert: "error",
  watchlist_batch: "warning",
  daily_digest: "info",
  archive_only: "neutral",
  suppressed: "neutral",
};

function MetadataRow({ label, value }: { label: string; value: unknown }) {
  const displayValue =
    value === null || value === undefined || value === "" ? "-" : String(value);
  return (
    <div className="flex justify-between gap-4 border-b border-zinc-800/60 py-1.5 text-sm">
      <span className="text-base-content/60">{label}</span>
      <span className="text-right font-medium text-zinc-200">{displayValue}</span>
    </div>
  );
}

export function AlertDetailPanel({
  alert,
  eventDetail,
  alertError,
  eventError,
  retry,
}: {
  alert?: AlertDecision;
  eventDetail?: EventDetail;
  alertError?: string;
  eventError?: string;
  retry: () => Promise<void>;
}) {
  if (alertError) {
    return <SectionError title="Alert detail unavailable" message={alertError} retry={retry} />;
  }

  if (!alert) {
    return (
      <EmptyState
        icon={Bell}
        title="No alert selected"
        body="Select an alert decision to inspect its metadata and related event context."
      />
    );
  }

  const headline = alert.event?.headline ?? alert.reason;
  const scoreBreakdown = Object.entries(alert.score_breakdown ?? {});

  // Filter out non-numeric structures (like llm analysis & agent investigation details) from the core grid
  const numericBreakdown = scoreBreakdown.filter(
    ([key]) => key !== "llm" && key !== "investigation"
  );

  const finalScore = alert.score_breakdown?.final_score ?? alert.event?.final_score;
  const deterministicScore = alert.score_breakdown?.deterministic_final_score;

  const llmData = alert.score_breakdown?.llm;
  const investigationData = alert.score_breakdown?.investigation;

  const badgeTone = decisionTones[alert.decision] || "neutral";

  return (
    <div className="space-y-5">
      <div>
        <Badge tone={badgeTone}>
          {formatLabel(alert.decision)}
        </Badge>
        <h2 className="mt-2 text-xl font-bold text-zinc-100">{headline}</h2>
        <p className="mt-1 text-sm text-base-content/70">{alert.reason}</p>
      </div>

      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Metadata</h3>
        <div className="grid gap-1">
          <MetadataRow label="Alert ID" value={alert.id} />
          <MetadataRow label="Event ID" value={alert.event_cluster_id} />
          <MetadataRow label="Decision" value={formatLabel(alert.decision)} />
          <MetadataRow label="Channel" value={alert.channel} />
          <MetadataRow label="Sent" value={formatTime(alert.sent_at)} />
          <MetadataRow label="Created" value={formatTime(alert.created_at)} />
          <MetadataRow label="Acknowledged" value={formatTime(alert.acknowledged_at)} />
          <MetadataRow label="Suppression" value={alert.suppression_reason} />
          <MetadataRow label="Delivery" value={alert.latest_delivery_status} />
          <MetadataRow label="Delivery error" value={alert.latest_delivery_error} />
          <MetadataRow label="Event status" value={alert.event?.status} />
          <MetadataRow label="Event score" value={alert.event?.final_score} />
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Score breakdown</h3>
        <div className="mb-3 rounded-lg border border-zinc-800 bg-gradient-to-r from-indigo-950/20 to-purple-950/20 p-4 flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-indigo-300">final score</div>
            <div className="mt-1 text-xs text-zinc-400">Deterministic first, adjusted by overrides</div>
          </div>
          <div className="flex items-baseline gap-2">
            {deterministicScore !== undefined && deterministicScore !== finalScore && (
              <span className="text-sm line-through text-zinc-500">
                {deterministicScore}
              </span>
            )}
            <span className="text-3xl font-extrabold text-indigo-400">
              {finalScore ?? "-"}
            </span>
          </div>
        </div>

        {numericBreakdown.length ? (
          <div className="grid gap-2 grid-cols-2 sm:grid-cols-3">
            {numericBreakdown.map(([key, value]) => {
              if (key === "final_score" || key === "deterministic_final_score") return null;
              const valNum = Number(value);
              const isPenalty = key.includes("penalty");
              const isZero = valNum === 0;

              let displayVal = String(value);
              let valColor = "text-zinc-100";
              if (isPenalty) {
                if (!isZero) {
                  displayVal = `-${value}`;
                  valColor = "text-red-400";
                } else {
                  valColor = "text-zinc-500 font-normal";
                }
              }

              return (
                <div
                  className="rounded-md border border-zinc-800 bg-zinc-950/30 p-2.5"
                  key={key}
                >
                  <div className="text-[10px] font-bold uppercase tracking-wider text-base-content/40 truncate">
                    {formatLabel(key)}
                  </div>
                  <div className={`mt-0.5 text-base font-bold ${valColor}`}>{displayVal}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-sm text-base-content/60">No score metrics recorded.</div>
        )}
      </section>

      {llmData && (
        <section className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 space-y-3">
          <div className="flex items-center justify-between border-b border-zinc-800/60 pb-2">
            <h3 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-purple-500 animate-pulse" />
              AI Analysis &amp; Insights
            </h3>
            {llmData.confidence && (
              <span className="text-xs font-semibold text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/20">
                Confidence: {llmData.confidence}
              </span>
            )}
          </div>

          {llmData.summary && (
            <div className="text-sm text-zinc-300 leading-relaxed italic bg-zinc-950/20 p-3 rounded border border-zinc-800/40 font-serif">
              &ldquo;{llmData.summary}&rdquo;
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-2 text-xs">
            {llmData.event_type && (
              <div className="col-span-full border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Event Type</span>
                <span className="text-zinc-300 leading-relaxed">{formatLabel(llmData.event_type)}</span>
              </div>
            )}
            {llmData.status_assessment && (
              <div className="col-span-full border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Status</span>
                <span className="text-zinc-300 leading-relaxed">{llmData.status_assessment}</span>
              </div>
            )}
            {llmData.score_modifier !== undefined && llmData.score_modifier !== 0 && (
              <div className="border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5 col-span-full sm:col-span-1">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Score Modifier</span>
                <span className={`font-bold text-xs ${llmData.score_modifier > 0 ? "text-green-400" : "text-red-400"}`}>
                  {llmData.score_modifier > 0 ? `+${llmData.score_modifier}` : llmData.score_modifier}
                </span>
              </div>
            )}
            {llmData.modifier_reason && (
              <div className="col-span-full border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Modifier Reason</span>
                <span className="text-zinc-300 leading-relaxed">{llmData.modifier_reason}</span>
              </div>
            )}
          </div>

          {llmData.why_it_matters && (
            <div className="text-xs">
              <span className="text-base-content/50 block font-bold mb-1 uppercase tracking-wider text-[9px]">Why it matters</span>
              <p className="text-zinc-300 bg-zinc-900/30 p-2.5 rounded border border-zinc-800/50 leading-relaxed">{llmData.why_it_matters}</p>
            </div>
          )}

          {llmData.risk_flags && llmData.risk_flags.length > 0 && (
            <div className="flex flex-col gap-2 pt-1">
              {llmData.risk_flags.map((flag: string) => (
                <div key={flag} className="flex items-start gap-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-2 text-red-400 text-[11px] leading-relaxed">
                  <span className="shrink-0">⚠️</span>
                  <span>{flag}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {investigationData && (
        <section className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 space-y-3">
          <div className="flex items-center justify-between border-b border-zinc-800/60 pb-2">
            <h3 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Agent Investigation
            </h3>
            {investigationData.confidence && (
              <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                Confidence: {investigationData.confidence}
              </span>
            )}
          </div>

          {investigationData.summary && (
            <div className="text-sm text-zinc-300 bg-zinc-950/20 p-3 rounded border border-zinc-800/40">
              {investigationData.summary}
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-2 text-xs">
            {investigationData.official_confirmation !== undefined && (
              <div className="col-span-full border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Official Confirmation</span>
                <span className="text-zinc-300 leading-relaxed">
                  {typeof investigationData.official_confirmation === "boolean"
                    ? investigationData.official_confirmation ? "✅ Confirmed" : "❌ Unconfirmed"
                    : String(investigationData.official_confirmation)}
                </span>
              </div>
            )}
            {investigationData.suggested_alert_level && (
              <div className="border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Suggested Alert Level</span>
                <span className="font-semibold text-emerald-400 text-xs uppercase">{formatLabel(investigationData.suggested_alert_level)}</span>
              </div>
            )}
            {investigationData.suggested_score_modifier !== undefined && investigationData.suggested_score_modifier !== 0 && (
              <div className="border-b border-zinc-800/40 py-1.5 flex flex-col gap-0.5">
                <span className="text-base-content/50 font-bold uppercase tracking-wider text-[9px]">Suggested Score Modifier</span>
                <span className={`font-bold text-xs ${investigationData.suggested_score_modifier > 0 ? "text-green-400" : "text-red-400"}`}>
                  {investigationData.suggested_score_modifier > 0 ? `+${investigationData.suggested_score_modifier}` : investigationData.suggested_score_modifier}
                </span>
              </div>
            )}
          </div>

          {investigationData.caveats && investigationData.caveats.length > 0 && (
            <div className="text-xs">
              <span className="text-base-content/50 block font-bold mb-1 uppercase tracking-wider text-[9px]">Caveats</span>
              <ul className="list-disc pl-4 space-y-1 text-zinc-300 leading-relaxed">
                {investigationData.caveats.map((caveat: string, idx: number) => (
                  <li key={idx}>{caveat}</li>
                ))}
              </ul>
            </div>
          )}

          {investigationData.risk_flags && investigationData.risk_flags.length > 0 && (
            <div className="flex flex-col gap-2 pt-1">
              {investigationData.risk_flags.map((flag: string) => (
                <div key={flag} className="flex items-start gap-2 rounded border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-yellow-400 text-[11px] leading-relaxed">
                  <span className="shrink-0">⚠️</span>
                  <span>{flag}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Related event</h3>
        {eventError ? (
          <SectionError title="Related event unavailable" message={eventError} retry={retry} />
        ) : eventDetail ? (
          <div className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm">
            <div className="font-semibold text-zinc-100">{eventDetail.canonical_headline}</div>
            <div className="mt-1 text-base-content/70">
              {eventDetail.summary ?? "No event summary yet."}
            </div>
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-base-content/60">
              <span>{eventDetail.status}</span>
              <span>{eventDetail.source_count} sources</span>
              <span>{eventDetail.final_score} score</span>
            </div>
          </div>
        ) : (
          <EmptyState
            icon={Database}
            title="Related event loading"
            body="Event metadata and linked news will appear after the event detail loads."
          />
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-bold text-zinc-100">Related news</h3>
        {eventDetail?.timeline.length ? (
          <div className="space-y-2">
            {eventDetail.timeline.map((item) => (
              <a
                className="block rounded-md border border-zinc-800 bg-zinc-950/30 p-3 text-sm hover:border-primary/40"
                href={item.url}
                key={item.news_item_id}
              >
                <div className="font-semibold text-zinc-100">{item.title}</div>
                <div className="mt-1 text-xs text-base-content/60">
                  {item.source_name} · {item.relation_type} · {item.similarity_score ?? "-"}
                </div>
                <div className="mt-1 text-xs text-base-content/50">
                  {formatTime(item.published_at ?? item.fetched_at ?? item.added_at)}
                </div>
              </a>
            ))}
          </div>
        ) : (
          <div className="text-sm text-base-content/60">
            No related news has been attached to this alert event yet.
          </div>
        )}
      </section>
    </div>
  );
}
