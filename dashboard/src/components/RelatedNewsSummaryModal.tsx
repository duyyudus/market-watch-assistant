import { Brain, FileText, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api, type EventRelatedNewsSummary } from "../api";

export function RelatedNewsSummaryModal({
  eventId,
  headline,
  open,
  onClose,
}: {
  eventId?: string;
  headline?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [summary, setSummary] = useState<EventRelatedNewsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !eventId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSummary(null);

    api
      .relatedNewsSummary(eventId)
      .then((value) => {
        if (!cancelled) setSummary(value);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to summarize related news");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [eventId, open]);

  useEffect(() => {
    if (!open) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        aria-label="Related news summary"
        aria-modal="true"
        className="flex max-h-[min(760px,calc(100vh-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 text-left shadow-2xl shadow-black/50"
        role="dialog"
      >
        <div className="shrink-0 flex items-start justify-between gap-3 border-b border-zinc-800 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-primary">
              <Brain className="h-4 w-4" />
              Summary
            </div>
            <h2 className="mt-1 text-base font-bold leading-6 text-zinc-100">
              {headline || "Related news"}
            </h2>
          </div>
          <button
            aria-label="Close summary"
            className="btn btn-square btn-ghost btn-sm shrink-0"
            onClick={onClose}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          {loading ? (
            <div className="flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-900/70 px-4 py-3 text-sm text-base-content/70">
              <span className="loading loading-spinner loading-sm" />
              Summarizing related news...
            </div>
          ) : error ? (
            <div className="rounded-md border border-error/30 bg-error/10 p-3 text-sm text-error">
              {error}
            </div>
          ) : summary?.status === "no_full_text" ? (
            <div className="space-y-3">
              <div className="rounded-md border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
                {summary.message ||
                  "At least one related news item needs full article text before a summary can be generated."}
              </div>
              <SourceCounts summary={summary} />
            </div>
          ) : summary ? (
            <div className="space-y-4">
              <SourceCounts summary={summary} />
              {summary.summary ? (
                <p className="rounded-md border border-zinc-800 bg-zinc-900/70 p-4 text-sm leading-relaxed text-zinc-200">
                  {summary.summary}
                </p>
              ) : null}
              {summary.digest_bullets.length ? (
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">Key points</h3>
                  <ul className="space-y-2 text-sm text-zinc-300">
                    {summary.digest_bullets.map((item) => (
                      <li className="rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2" key={item}>
                        {item}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {summary.why_it_matters ? (
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">Why it matters</h3>
                  <p className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3 text-sm leading-relaxed text-zinc-300">
                    {summary.why_it_matters}
                  </p>
                </section>
              ) : null}
              {summary.caveats.length ? (
                <section>
                  <h3 className="mb-2 text-sm font-bold text-zinc-100">Evidence notes</h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-base-content/70">
                    {summary.caveats.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          ) : (
            <div className="rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-base-content/60">
              Summary is ready to load.
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function SourceCounts({ summary }: { summary: EventRelatedNewsSummary }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-base-content/60">
      <span className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1">
        <FileText className="h-3.5 w-3.5" />
        {summary.news_item_count} related news
      </span>
      <span className="rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1">
        {summary.full_text_item_count} with full text
      </span>
    </div>
  );
}
