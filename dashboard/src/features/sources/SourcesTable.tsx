import { Plus, Radio, RefreshCcw } from "lucide-react";
import { useRef, useState } from "react";

import {
  api,
  type ConfigurationPresets,
  type Source,
  type SourceArticlePreviewResponse,
  type SourceHealth,
  type SourcePayload,
  type SourcePreviewItem,
  type SourcePreviewResponse,
} from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { FeatureTabs } from "../../components/FeatureTabs";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { useSortableData } from "../../hooks/useSortableData";
import type { QueueCommand } from "../../types/dashboard";
import { SourceConfiguredList } from "./SourceConfiguredList";
import { SourceForm, emptySourcePayload } from "./SourceForm";
import { SourceHealthPanel } from "./SourceHealthPanel";

export function SourcesTable({
  rows,
  health,
  error,
  presets,
  reload,
  queue,
}: {
  rows: Source[];
  health: SourceHealth[];
  error?: string;
  presets: ConfigurationPresets["sources"] | null;
  reload: () => Promise<void>;
  queue: QueueCommand;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "name",
    direction: "asc",
  });
  const [editing, setEditing] = useState<Source | "new" | null>(null);
  const [form, setForm] = useState<SourcePayload>(emptySourcePayload());
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [subTab, setSubTab] = useState<"configured" | "health">("configured");
  const [preview, setPreview] = useState<SourcePreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedPreviewItem, setSelectedPreviewItem] = useState<SourcePreviewItem | null>(null);
  const [articlePreview, setArticlePreview] = useState<SourceArticlePreviewResponse | null>(null);
  const [articleError, setArticleError] = useState<string | null>(null);
  const [articleLoadingUrl, setArticleLoadingUrl] = useState<string | null>(null);
  const previewRequestId = useRef(0);
  const articleRequestId = useRef(0);
  const allSourcesEnabled = rows.length > 0 && rows.every((row) => row.enabled);

  function resetPreview() {
    previewRequestId.current += 1;
    articleRequestId.current += 1;
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
    setSelectedPreviewItem(null);
    setArticlePreview(null);
    setArticleError(null);
    setArticleLoadingUrl(null);
  }

  async function toggle(row: Source) {
    setBulkError(null);
    try {
      await api.setSourceEnabled(row.id, !row.enabled);
      await reload();
    } catch (error) {
      setBulkError(error instanceof Error ? error.message : "Unable to update source");
    }
  }

  async function toggleAll() {
    if (!rows.length) {
      return;
    }
    setBulkSaving(true);
    setBulkError(null);
    try {
      await api.setAllSourcesEnabled(!allSourcesEnabled);
      await reload();
    } catch (error) {
      setBulkError(error instanceof Error ? error.message : "Unable to update sources");
    } finally {
      setBulkSaving(false);
    }
  }

  function startCreate() {
    setEditing("new");
    setForm(emptySourcePayload(presets));
    setFormError(null);
    resetPreview();
  }

  function startEdit(row: Source) {
    setEditing(row);
    setForm({
      name: row.name,
      url: row.url,
      source_type: row.source_type,
      category: row.category,
      region: row.region,
      language: row.language,
      source_score: row.source_score,
      polling_interval_seconds: row.polling_interval_seconds,
      enabled: row.enabled,
    });
    setFormError(null);
    resetPreview();
  }

  async function saveSource() {
    setSaving(true);
    setFormError(null);
    try {
      if (editing === "new") {
        await api.createSource(form);
      } else if (editing) {
        await api.updateSource(editing.id, form);
      }
      setEditing(null);
      resetPreview();
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to save source");
    } finally {
      setSaving(false);
    }
  }

  async function pollPreview() {
    const url = form.url.trim();
    if (!url) {
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    setSelectedPreviewItem(null);
    setArticlePreview(null);
    setArticleError(null);
    const requestId = previewRequestId.current + 1;
    previewRequestId.current = requestId;
    try {
      const result = await api.previewSource({
        url,
        source_type: form.source_type,
        limit: 10,
      });
      if (requestId !== previewRequestId.current) {
        return;
      }
      setPreview(result);
      if (result.status === "error") {
        setPreviewError(result.error_message ?? "Unable to preview source");
      }
    } catch (error) {
      if (requestId !== previewRequestId.current) {
        return;
      }
      setPreview(null);
      setPreviewError(error instanceof Error ? error.message : "Unable to preview source");
    } finally {
      if (requestId === previewRequestId.current) {
        setPreviewLoading(false);
      }
    }
  }

  async function previewArticle(item: SourcePreviewItem) {
    setSelectedPreviewItem(item);
    setArticleLoadingUrl(item.url);
    setArticleError(null);
    const requestId = articleRequestId.current + 1;
    articleRequestId.current = requestId;
    try {
      const result = await api.previewSourceArticle({
        url: item.url,
        source_type: form.source_type,
        fallback_snippet: item.description,
        fallback_title: item.title,
        max_chars: 20000,
      });
      if (requestId !== articleRequestId.current) {
        return;
      }
      setArticlePreview(result);
      if (result.status === "error") {
        setArticleError(result.error_message ?? "Unable to preview article");
      }
    } catch (error) {
      if (requestId !== articleRequestId.current) {
        return;
      }
      setArticlePreview(null);
      setArticleError(error instanceof Error ? error.message : "Unable to preview article");
    } finally {
      if (requestId === articleRequestId.current) {
        setArticleLoadingUrl(null);
      }
    }
  }

  return (
    <Panel title="Sources">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <FeatureTabs
          activeTab={subTab}
          onChange={setSubTab}
          tabs={[
            { id: "configured", label: "Configured" },
            { id: "health", label: "Health" },
          ]}
        />
        <div className="flex flex-wrap items-center gap-3">
          {rows.length ? (
            <label className="label cursor-pointer gap-2 rounded-md border border-zinc-800/60 bg-zinc-950/40 px-3 py-1.5">
              <span className="label-text text-xs font-semibold text-zinc-300">All sources</span>
              <input
                aria-label="All sources"
                checked={allSourcesEnabled}
                className="toggle toggle-sm"
                disabled={bulkSaving}
                onChange={() => void toggleAll()}
                type="checkbox"
              />
            </label>
          ) : null}
          <button className="btn btn-sm btn-primary" onClick={startCreate} type="button">
            <Plus className="h-4 w-4" />
            Add source
          </button>
        </div>
      </div>
      {bulkError ? <div className="alert alert-error mb-4 text-sm">{bulkError}</div> : null}
      {editing ? (
        <SourceForm
          key={editing === "new" ? "new" : editing.id}
          form={form}
          formError={formError}
          isNew={editing === "new"}
          presets={presets}
          saving={saving}
          setForm={setForm}
          preview={preview}
          previewError={previewError}
          previewLoading={previewLoading}
          selectedPreviewItem={selectedPreviewItem}
          articlePreview={articlePreview}
          articleError={articleError}
          articleLoadingUrl={articleLoadingUrl}
          onCancel={() => {
            setEditing(null);
            resetPreview();
          }}
          onFormChange={resetPreview}
          onPollPreview={pollPreview}
          onPreviewArticle={previewArticle}
          onSave={saveSource}
        />
      ) : null}
      {subTab === "health" ? (
        <SourceHealthPanel
          health={health}
          sources={rows}
          queue={queue}
          reload={reload}
          toggle={toggle}
        />
      ) : error ? (
        <SectionError title="Sources unavailable" message={error} retry={reload} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Radio}
          title="No sources configured"
          body="Source configuration will appear here after feed sources are added to the shared database."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void reload()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <SourceConfiguredList
          sources={sortedRows}
          sortKey={sortConfig.key}
          sortDirection={sortConfig.direction}
          onSort={requestSort}
          onEdit={startEdit}
          onToggle={(source) => void toggle(source)}
        />
      )}
    </Panel>
  );
}
