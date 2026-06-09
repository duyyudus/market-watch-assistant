import { ChevronLeft, ChevronRight, ExternalLink, Newspaper, RefreshCcw } from "lucide-react";

import type { NewsDetail, NewsItem, Source } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { ResponsiveDataList } from "../../components/ResponsiveDataList";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";
import { formatTime } from "../../lib/time";

const LIMIT_OPTIONS = [25, 50, 100, 200];
const noopRetry = async () => undefined;

export function NewsTable({
  rows,
  error,
  detailError,
  retry,
  selectedNewsId,
  selectedNewsDetail,
  selectNews,
  limit,
  setLimit,
  offset,
  total,
  setOffset,
  domain,
  setDomain,
  domainOptions,
  sourceId,
  setSourceId,
  sourceOptions,
  status,
  setStatus,
  statusOptions,
  region,
  setRegion,
  regionOptions,
}: {
  rows: NewsItem[];
  error?: string;
  detailError?: string;
  retry: () => Promise<void>;
  selectedNewsId: string | null;
  selectedNewsDetail: NewsDetail | null;
  selectNews: (id: string) => void;
  limit: number;
  setLimit: (limit: number) => void;
  offset: number;
  total: number;
  setOffset: (offset: number) => void;
  domain: string;
  setDomain: (domain: string) => void;
  domainOptions: string[];
  sourceId: string;
  setSourceId: (sourceId: string) => void;
  sourceOptions: Array<Pick<Source, "id" | "name" | "source_type">>;
  status: string;
  setStatus: (status: string) => void;
  statusOptions: string[];
  region: string;
  setRegion: (region: string) => void;
  regionOptions: string[];
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "time",
    direction: "desc",
  });
  const pageStart = total > 0 ? Math.min(offset + 1, total) : 0;
  const pageEnd = Math.min(offset + limit, total);
  const canGoPrevious = offset > 0;
  const canGoNext = offset + limit < total;

  return (
    <Panel title="Normalized news">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <label className="form-control w-full min-w-44">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Source domain</span>
            </span>
            <select
              aria-label="Source domain"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) => setDomain(event.target.value)}
              value={domain}
            >
              <option value="">All domains</option>
              {domain && !domainOptions.includes(domain) ? (
                <option value={domain}>{domain}</option>
              ) : null}
              {domainOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="form-control w-full min-w-44">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Source</span>
            </span>
            <select
              aria-label="Source"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) => setSourceId(event.target.value)}
              value={sourceId}
            >
              <option value="">All sources</option>
              {sourceId && !sourceOptions.some((option) => option.id === sourceId) ? (
                <option value={sourceId}>{sourceId}</option>
              ) : null}
              {sourceOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name} · {option.source_type}
                </option>
              ))}
            </select>
          </label>
          <label className="form-control w-full min-w-36">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Status</span>
            </span>
            <select
              aria-label="Status"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              <option value="">All statuses</option>
              {status && !statusOptions.includes(status) ? <option value={status}>{status}</option> : null}
              {statusOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="form-control w-full min-w-36">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Region</span>
            </span>
            <select
              aria-label="Region"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) => setRegion(event.target.value)}
              value={region}
            >
              <option value="">All regions</option>
              {region && !regionOptions.includes(region) ? <option value={region}>{region}</option> : null}
              {regionOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="form-control w-full min-w-36">
            <span className="label pb-1">
              <span className="label-text text-xs font-semibold text-zinc-400">Items per page</span>
            </span>
            <select
              aria-label="Items per page"
              className="select select-bordered select-sm w-full bg-zinc-950"
              onChange={(event) => setLimit(Number(event.target.value))}
              value={limit}
            >
              {LIMIT_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          className="btn btn-sm btn-outline self-start lg:self-end"
          onClick={() => void retry()}
          type="button"
        >
          <RefreshCcw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {error ? (
        <SectionError title="Normalized news unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Newspaper}
          title="No normalized news yet"
          body="Ingested news will appear here after source fetch and normalization jobs run."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_570px]">
          <div className="min-w-0">
            <ResponsiveDataList
              cards={sortedRows.map((row) => (
                <button
                  className={classNames(
                    "w-full rounded-md border p-3 text-left transition-colors",
                    row.id === selectedNewsId
                      ? "border-primary/70 bg-primary/10"
                      : "border-zinc-800 bg-zinc-950/30 hover:border-zinc-700",
                  )}
                  data-testid={`news-card-${row.id}`}
                  key={row.id}
                  onClick={() => selectNews(row.id)}
                  type="button"
                >
                  <div className="text-sm font-semibold text-zinc-100">{row.title}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-base-content/60">
                    <span>{row.source_name}</span>
                    <span>{row.processing_status}</span>
                    <span>{row.region}</span>
                  </div>
                  <div className="mt-2 text-xs text-zinc-500">
                    {formatTime(row.published_at ?? row.fetched_at)}
                  </div>
                </button>
              ))}
              table={
                <table className="table w-full">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                      <SortableHeader
                        label="Title"
                        sortKey="title"
                        currentSortKey={sortConfig.key}
                        direction={sortConfig.direction}
                        onSort={requestSort}
                      />
                      <SortableHeader
                        label="Source"
                        sortKey="source_name"
                        currentSortKey={sortConfig.key}
                        direction={sortConfig.direction}
                        onSort={requestSort}
                      />
                      <SortableHeader
                        label="Status"
                        sortKey="processing_status"
                        currentSortKey={sortConfig.key}
                        direction={sortConfig.direction}
                        onSort={requestSort}
                      />
                      <SortableHeader
                        label="Region"
                        sortKey="region"
                        currentSortKey={sortConfig.key}
                        direction={sortConfig.direction}
                        onSort={requestSort}
                      />
                      <SortableHeader
                        label="Time"
                        sortKey="time"
                        currentSortKey={sortConfig.key}
                        direction={sortConfig.direction}
                        onSort={requestSort}
                      />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/40">
                    {sortedRows.map((row) => (
                      <tr
                        className={classNames(
                          "cursor-pointer border-b border-zinc-800/30 transition-colors hover:bg-zinc-900/60",
                          row.id === selectedNewsId ? "bg-primary/10" : "",
                        )}
                        data-testid={`news-row-${row.id}`}
                        key={row.id}
                        onClick={() => selectNews(row.id)}
                      >
                        <td className="py-3 px-4 max-w-[560px] whitespace-normal text-sm font-semibold text-zinc-200">
                          {row.title}
                        </td>
                        <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                          {row.source_name}
                        </td>
                        <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                          {row.processing_status}
                        </td>
                        <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                        <td className="py-3 px-4 text-zinc-500 font-normal text-xs">
                          {formatTime(row.published_at ?? row.fetched_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              }
            />
            <div className="mt-4 flex flex-col gap-2 border-t border-zinc-800/60 pt-3 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
              <span>
                {pageStart}-{pageEnd} of {total}
              </span>
              <div className="join">
                <button
                  aria-label="Previous page"
                  className="btn join-item btn-sm btn-outline"
                  disabled={!canGoPrevious}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  type="button"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  aria-label="Next page"
                  className="btn join-item btn-sm btn-outline"
                  disabled={!canGoNext}
                  onClick={() => setOffset(offset + limit)}
                  type="button"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
          <NewsDetailPanel
            detail={selectedNewsDetail}
            detailError={detailError}
            isLoading={Boolean(selectedNewsId && !selectedNewsDetail && !detailError)}
          />
        </div>
      )}
    </Panel>
  );
}

function NewsDetailPanel({
  detail,
  detailError,
  isLoading,
}: {
  detail: NewsDetail | null;
  detailError?: string;
  isLoading: boolean;
}) {
  if (detailError) {
    return <SectionError title="Article detail unavailable" message={detailError} retry={noopRetry} />;
  }
  if (isLoading) {
    return (
      <aside className="rounded-md border border-zinc-800 bg-zinc-950/30 p-4">
        <div className="loading loading-spinner loading-sm" />
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="rounded-md border border-zinc-800 bg-zinc-950/30 p-4">
        <h3 className="text-sm font-bold text-zinc-100">Article detail</h3>
        <p className="mt-2 text-sm text-zinc-500">Select a normalized news item to inspect article metadata.</p>
      </aside>
    );
  }

  return (
    <aside className="h-fit rounded-md border border-zinc-800 bg-zinc-950/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-zinc-100">Article detail</h3>
          <p className="mt-1 text-sm font-semibold leading-snug text-zinc-200">{detail.title}</p>
        </div>
        <a
          aria-label="Open article"
          className="btn btn-square btn-ghost btn-sm shrink-0"
          href={detail.canonical_url ?? detail.url}
          rel="noreferrer"
          target="_blank"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      <div className="mt-4 grid gap-2 text-xs">
        <DetailRow label="Source" value={detail.source_name} />
        <DetailRow label="Domain" value={domainFor(detail.canonical_url ?? detail.url)} />
        <DetailRow label="Status" value={detail.processing_status} />
        <DetailRow label="Region" value={detail.region} />
        <DetailRow label="Language" value={detail.language} />
        <DetailRow label="Assets" value={detail.asset_classes.join(", ") || "-"} />
        <DetailRow label="Published" value={formatTime(detail.published_at)} />
        <DetailRow label="Fetched" value={formatTime(detail.fetched_at)} />
        <DetailRow label="Paywalled" value={detail.is_paywalled ? "yes" : "no"} />
        <DetailRow
          label="Full text"
          value={`${detail.full_text_available ? "available" : "unavailable"} · ${detail.full_text_extraction_status}`}
        />
        <DetailRow label="HTTP" value={String(detail.full_text_last_http_status ?? "-")} />
      </div>

      <DetailSection title="Snippet" body={detail.snippet || "No snippet available."} />
      <DetailSection title="Full text" body={detail.raw_content || "No full article text available."} scrollable />

      <div className="mt-4">
        <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Entities</h4>
        <div className="mt-2 flex flex-wrap gap-2">
          {detail.entities.length > 0 ? (
            detail.entities.map((entity) => (
              <span
                className="inline-flex max-w-full items-start gap-1 rounded-full border border-zinc-600 px-2.5 py-1 text-xs leading-snug text-zinc-300"
                data-testid={`news-entity-${entity.id}`}
                key={entity.id}
              >
                <span className="min-w-0 whitespace-normal break-words">
                  {entity.normalized_name}
                </span>
                <span className="shrink-0 text-zinc-500">{entity.confidence}</span>
              </span>
            ))
          ) : (
            <span className="text-xs text-zinc-500">No entities extracted.</span>
          )}
        </div>
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Event clusters</h4>
        <div className="mt-2 space-y-2">
          {detail.clusters.length > 0 ? (
            detail.clusters.map((cluster) => (
              <div
                className="rounded border border-zinc-800 bg-zinc-950/50 p-2 text-xs"
                key={cluster.event_cluster_id}
              >
                <div className="font-semibold text-zinc-200">{cluster.event_cluster_id}</div>
                <div className="mt-1 text-zinc-500">
                  {cluster.relation_type} · {cluster.similarity_score ?? "-"}
                </div>
              </div>
            ))
          ) : (
            <span className="text-xs text-zinc-500">No event cluster links.</span>
          )}
        </div>
      </div>
    </aside>
  );
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-2">
      <span className="font-semibold text-zinc-500">{label}</span>
      <span className="break-words text-zinc-300">{value || "-"}</span>
    </div>
  );
}

function DetailSection({
  title,
  body,
  scrollable = false,
}: {
  title: string;
  body: string;
  scrollable?: boolean;
}) {
  return (
    <div className="mt-4">
      <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-500">{title}</h4>
      <pre
        className={classNames(
          "mt-2 whitespace-pre-wrap break-words rounded bg-zinc-950/70 p-3 text-xs leading-relaxed text-zinc-200",
          scrollable ? "max-h-[32rem] overflow-y-auto" : "",
        )}
      >
        {body}
      </pre>
    </div>
  );
}

function domainFor(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
