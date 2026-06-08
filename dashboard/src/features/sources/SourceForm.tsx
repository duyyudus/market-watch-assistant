import { FileText, RefreshCcw } from "lucide-react";
import { useEffect, useRef } from "react";

import type {
  ConfigurationPresets,
  SourceArticlePreviewResponse,
  SourcePayload,
  SourcePreviewItem,
  SourcePreviewResponse,
} from "../../api";
import { InlineEditPanel } from "../../components/InlineEditPanel";

export function SourceForm({
  form,
  formError,
  isNew,
  presets,
  saving,
  setForm,
  preview,
  previewError,
  previewLoading,
  articlePreview,
  articleError,
  articleLoadingUrl,
  selectedPreviewItem,
  onCancel,
  onFormChange,
  onPollPreview,
  onPreviewArticle,
  onSave,
}: {
  form: SourcePayload;
  formError: string | null;
  isNew: boolean;
  presets: ConfigurationPresets["sources"] | null;
  saving: boolean;
  setForm: (value: SourcePayload) => void;
  preview: SourcePreviewResponse | null;
  previewError: string | null;
  previewLoading: boolean;
  articlePreview: SourceArticlePreviewResponse | null;
  articleError: string | null;
  articleLoadingUrl: string | null;
  selectedPreviewItem: SourcePreviewItem | null;
  onCancel: () => void;
  onFormChange: () => void;
  onPollPreview: () => Promise<void>;
  onPreviewArticle: (item: SourcePreviewItem) => Promise<void>;
  onSave: () => Promise<void>;
}) {
  const formRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (formRef.current && typeof formRef.current.scrollIntoView === "function") {
      formRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  function update<K extends keyof SourcePayload>(key: K, value: SourcePayload[K]) {
    if (key === "url" || key === "source_type") {
      onFormChange();
    }
    setForm({ ...form, [key]: value });
  }

  const canPreview = form.url.trim().length > 0 && !previewLoading;

  return (
    <InlineEditPanel
      title={isNew ? "New source" : "Edit source"}
      error={formError}
      className="scroll-mt-20"
      panelRef={formRef}
      onCancel={onCancel}
    >
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label className="form-control">
          <span className="label-text">Source name</span>
          <input
            className="input input-bordered input-sm"
            onChange={(event) => update("name", event.target.value)}
            value={form.name}
          />
        </label>
        <label className="form-control md:col-span-2">
          <span className="label-text">Source URL</span>
          <div className="flex gap-2">
            <input
              className="input input-bordered input-sm min-w-0 flex-1"
              onChange={(event) => update("url", event.target.value)}
              value={form.url}
            />
            <button
              className="btn btn-sm btn-outline btn-primary shrink-0"
              disabled={!canPreview}
              onClick={() => void onPollPreview()}
              type="button"
            >
              <RefreshCcw className={`h-4 w-4 ${previewLoading ? "animate-spin" : ""}`} />
              Poll preview
            </button>
          </div>
        </label>
        <label className="form-control">
          <span className="label-text">Source type</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("source_type", event.target.value)}
            value={form.source_type}
          >
            {optionsFor(presets?.source_types ?? [], form.source_type).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Region</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("region", event.target.value)}
            value={form.region}
          >
            {optionsFor(presets?.regions ?? [], form.region).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Category</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("category", event.target.value)}
            value={form.category}
          >
            {optionsFor(presets?.categories ?? [], form.category).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Language</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("language", event.target.value)}
            value={form.language}
          >
            {optionsFor(presets?.languages ?? [], form.language).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Source score</span>
          <input
            className="input input-bordered input-sm"
            max={100}
            min={0}
            onChange={(event) => update("source_score", Number(event.target.value))}
            type="number"
            value={form.source_score}
          />
        </label>
        <label className="form-control">
          <span className="label-text">Polling interval</span>
          <input
            className="input input-bordered input-sm"
            min={60}
            onChange={(event) => update("polling_interval_seconds", Number(event.target.value))}
            type="number"
            value={form.polling_interval_seconds}
          />
        </label>
        <label className="label cursor-pointer justify-start gap-3 pt-7">
          <input
            checked={form.enabled}
            className="toggle toggle-sm"
            onChange={(event) => update("enabled", event.target.checked)}
            type="checkbox"
          />
          <span className="label-text">Enabled</span>
        </label>
      </div>
      <div className="mt-4 flex justify-end">
        <button
          className="btn btn-sm btn-primary"
          disabled={saving}
          onClick={() => void onSave()}
          type="button"
        >
          Save source
        </button>
      </div>
      <SourcePreviewPanel
        articleError={articleError}
        articleLoadingUrl={articleLoadingUrl}
        articlePreview={articlePreview}
        preview={preview}
        previewError={previewError}
        previewLoading={previewLoading}
        selectedPreviewItem={selectedPreviewItem}
        onPreviewArticle={onPreviewArticle}
      />
    </InlineEditPanel>
  );
}

export function emptySourcePayload(
  presets?: ConfigurationPresets["sources"] | null,
): SourcePayload {
  return {
    name: "",
    url: "",
    source_type: presets?.source_types[0] ?? "",
    category: presets?.categories[0] ?? "",
    region: presets?.regions[0] ?? "",
    language: presets?.languages[0] ?? "",
    source_score: 60,
    polling_interval_seconds: 300,
    enabled: true,
  };
}

function SourcePreviewPanel({
  preview,
  previewError,
  previewLoading,
  articlePreview,
  articleError,
  articleLoadingUrl,
  selectedPreviewItem,
  onPreviewArticle,
}: {
  preview: SourcePreviewResponse | null;
  previewError: string | null;
  previewLoading: boolean;
  articlePreview: SourceArticlePreviewResponse | null;
  articleError: string | null;
  articleLoadingUrl: string | null;
  selectedPreviewItem: SourcePreviewItem | null;
  onPreviewArticle: (item: SourcePreviewItem) => Promise<void>;
}) {
  if (!preview && !previewError && !previewLoading && !articlePreview && !articleError) {
    return null;
  }

  return (
    <div className="mt-4 border-t border-zinc-800/70 pt-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-bold uppercase text-zinc-400">Preview</div>
        {preview ? (
          <div className="text-xs text-base-content/60">
            {preview.status} · HTTP {preview.http_status ?? "-"} · {preview.duration_ms}ms ·{" "}
            {preview.item_count} items
          </div>
        ) : null}
      </div>
      {previewLoading ? (
        <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3 text-sm text-zinc-300">
          Polling source...
        </div>
      ) : null}
      {previewError ? <div className="alert alert-error mb-3 text-sm">{previewError}</div> : null}
      {preview && preview.items.length === 0 && !previewError ? (
        <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3 text-sm text-zinc-300">
          No RSS items were found.
        </div>
      ) : null}
      {preview && preview.items.length > 0 ? (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)] xl:h-[500px]">
          <div className="max-h-96 xl:max-h-none xl:h-full overflow-y-auto rounded-md border border-zinc-800">
            {preview.items.map((item) => {
              const isSelected =
                selectedPreviewItem?.url === item.url &&
                selectedPreviewItem?.title === item.title;
              return (
                <button
                  aria-label={`Preview article ${item.title}`}
                  className={`block w-full border-b border-zinc-800/60 border-l-2 p-3 text-left last:border-b-0 transition-all ${
                    isSelected
                      ? "border-l-primary bg-zinc-900/85 text-zinc-100"
                      : "border-l-transparent bg-zinc-950/30 hover:bg-zinc-900/70"
                  }`}
                  disabled={articleLoadingUrl === item.url}
                  key={`${item.guid ?? item.url}-${item.title}`}
                  onClick={() => void onPreviewArticle(item)}
                  type="button"
                >
                  <div className="flex items-start gap-2">
                    <FileText className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-zinc-100">
                        {item.title}
                      </div>
                      <div className="mt-1 truncate text-xs text-base-content/60">
                        {domainFor(item.url)}
                        {item.published_at ? ` · ${formatPreviewDate(item.published_at)}` : ""}
                      </div>
                      {item.description ? (
                        <div className="mt-2 line-clamp-2 text-xs text-zinc-400">
                          {item.description}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
          <ArticlePreviewPanel
            articleError={articleError}
            articleLoading={articleLoadingUrl !== null}
            articlePreview={articlePreview}
            selectedPreviewItem={selectedPreviewItem}
          />
        </div>
      ) : null}
    </div>
  );
}

function ArticlePreviewPanel({
  articlePreview,
  articleError,
  articleLoading,
  selectedPreviewItem,
}: {
  articlePreview: SourceArticlePreviewResponse | null;
  articleError: string | null;
  articleLoading: boolean;
  selectedPreviewItem: SourcePreviewItem | null;
}) {
  if (!articlePreview && !articleError && !articleLoading && !selectedPreviewItem) {
    return (
      <div className="rounded-md border border-zinc-800 bg-zinc-950/30 p-4 text-sm text-zinc-400 xl:h-full xl:flex xl:items-center xl:justify-center">
        Select an item to fetch article text.
      </div>
    );
  }
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/30 p-4 xl:h-full xl:flex xl:flex-col xl:min-h-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-base-content/60 shrink-0">
        <span className="font-bold uppercase text-zinc-400">Article</span>
        {articlePreview ? (
          <span>
            {articlePreview.status} · HTTP {articlePreview.http_status ?? "-"} ·{" "}
            {articlePreview.duration_ms}ms · {articlePreview.text_length} chars
          </span>
        ) : null}
      </div>
      {articleLoading ? (
        <div className="text-sm text-zinc-300 mb-3 shrink-0">Fetching article...</div>
      ) : null}
      {articleError ? (
        <div className="alert alert-error mb-3 text-sm shrink-0">{articleError}</div>
      ) : null}
      {selectedPreviewItem?.description ? (
        <div className="mb-3 rounded border border-zinc-800 bg-zinc-950/60 p-3 shrink-0">
          <div className="mb-1 text-xs font-bold uppercase text-zinc-400">Snippet</div>
          <div className="whitespace-pre-wrap break-words text-xs leading-relaxed text-zinc-200">
            {selectedPreviewItem.description}
          </div>
        </div>
      ) : null}
      {articlePreview ? (
        <div className="xl:flex-1 xl:flex xl:flex-col xl:min-h-0">
          {articlePreview.error_message ? (
            <div className="alert alert-warning mb-3 text-sm shrink-0">
              {articlePreview.error_message}
            </div>
          ) : null}
          {articlePreview.truncated ? (
            <div className="mb-2 text-xs font-semibold text-amber-400 shrink-0">
              Text truncated to preview limit.
            </div>
          ) : null}
          <pre className="max-h-80 whitespace-pre-wrap break-words overflow-y-auto rounded bg-zinc-950/70 p-3 text-xs leading-relaxed text-zinc-200 xl:max-h-none xl:flex-1 xl:min-h-0">
            {articlePreview.text || "No article text available."}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function optionsFor(options: string[], value: string): string[] {
  return value && !options.includes(value) ? [value, ...options] : options;
}

function domainFor(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatPreviewDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}
