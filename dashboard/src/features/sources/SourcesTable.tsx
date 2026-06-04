import { Pencil, Plus, Radio, RefreshCcw, X } from "lucide-react";
import { useState } from "react";

import {
  api,
  type ConfigurationPresets,
  type Source,
  type SourceHealth,
  type SourcePayload,
} from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";
import type { QueueCommand } from "../../types/dashboard";

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
  const allSourcesEnabled = rows.length > 0 && rows.every((row) => row.enabled);

  async function toggle(row: Source) {
    await api.setSourceEnabled(row.id, !row.enabled);
    await reload();
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
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to save source");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Sources">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="tabs tabs-boxed border border-zinc-800/60 bg-zinc-950/60 p-1">
          <button
            className={`tab tab-sm ${subTab === "configured" ? "tab-active" : ""}`}
            onClick={() => setSubTab("configured")}
            type="button"
          >
            Configured
          </button>
          <button
            className={`tab tab-sm ${subTab === "health" ? "tab-active" : ""}`}
            onClick={() => setSubTab("health")}
            type="button"
          >
            Health
          </button>
        </div>
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
          form={form}
          formError={formError}
          isNew={editing === "new"}
          presets={presets}
          saving={saving}
          setForm={setForm}
          onCancel={() => setEditing(null)}
          onSave={saveSource}
        />
      ) : null}
      {subTab === "health" ? (
        <SourceHealthPanel health={health} rows={rows} queue={queue} reload={reload} toggle={toggle} />
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
        <>
        <div className="grid gap-3 lg:hidden">
          {sortedRows.map((row) => (
            <div
              className="rounded-md border border-zinc-800 bg-zinc-950/30 p-3"
              data-testid={`source-card-${row.id}`}
              key={row.id}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold text-zinc-100">{row.name}</div>
                <input
                  aria-label={`${row.enabled ? "Disable" : "Enable"} ${row.name}`}
                  className="toggle toggle-sm"
                  checked={row.enabled}
                  onChange={() => void toggle(row)}
                  type="checkbox"
                />
              </div>
              <div className="mt-2 text-xs text-base-content/60">
                {row.region} · {row.category} · {row.polling_interval_seconds}s
              </div>
              <button
                aria-label={`Edit ${row.name}`}
                className="btn btn-xs btn-outline btn-primary mt-3"
                onClick={() => startEdit(row)}
                type="button"
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit
              </button>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto lg:block">
          <table className="table w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500 text-xs uppercase tracking-wider">
                <SortableHeader
                  label="Name"
                  sortKey="name"
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
                  label="Category"
                  sortKey="category"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Score"
                  sortKey="source_score"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Interval"
                  sortKey="polling_interval_seconds"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Enabled"
                  sortKey="enabled"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <th className="px-4 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => (
                <tr key={row.id} className="border-b border-zinc-800/30">
                  <td className="py-3 px-4 text-sm font-semibold text-zinc-200">{row.name}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.region}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">{row.category}</td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.source_score}
                  </td>
                  <td className="py-3 px-4 text-zinc-400 font-normal text-xs">
                    {row.polling_interval_seconds}s
                  </td>
                  <td className="py-3 px-4">
                    <input
                      aria-label={`${row.enabled ? "Disable" : "Enable"} ${row.name}`}
                      className="toggle toggle-sm"
                      checked={row.enabled}
                      onChange={() => void toggle(row)}
                      type="checkbox"
                    />
                  </td>
                  <td className="py-3 px-4">
                    <button
                      aria-label={`Edit ${row.name}`}
                      className="btn btn-xs btn-ghost"
                      onClick={() => startEdit(row)}
                      type="button"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
    </Panel>
  );
}

function SourceHealthPanel({
  health,
  rows,
  queue,
  reload,
  toggle,
}: {
  health: SourceHealth[];
  rows: Source[];
  queue: QueueCommand;
  reload: () => Promise<void>;
  toggle: (row: Source) => Promise<void>;
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
    <div className="grid gap-3 xl:grid-cols-2">
      {health.map((row) => {
        const source = rows.find((item) => item.id === row.source_id);
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

function emptySourcePayload(presets?: ConfigurationPresets["sources"] | null): SourcePayload {
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

function SourceForm({
  form,
  formError,
  isNew,
  presets,
  saving,
  setForm,
  onCancel,
  onSave,
}: {
  form: SourcePayload;
  formError: string | null;
  isNew: boolean;
  presets: ConfigurationPresets["sources"] | null;
  saving: boolean;
  setForm: (value: SourcePayload) => void;
  onCancel: () => void;
  onSave: () => Promise<void>;
}) {
  function update<K extends keyof SourcePayload>(key: K, value: SourcePayload[K]) {
    setForm({ ...form, [key]: value });
  }

  return (
    <div className="mb-5 rounded-md border border-zinc-800 bg-zinc-950/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-zinc-200">
          {isNew ? "New source" : "Edit source"}
        </div>
        <button className="btn btn-xs btn-ghost" onClick={onCancel} type="button">
          <X className="h-4 w-4" />
          Cancel
        </button>
      </div>
      {formError ? <div className="alert alert-error mb-3 text-sm">{formError}</div> : null}
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
          <input
            className="input input-bordered input-sm"
            onChange={(event) => update("url", event.target.value)}
            value={form.url}
          />
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
    </div>
  );
}

function optionsFor(options: string[], value: string): string[] {
  return value && !options.includes(value) ? [value, ...options] : options;
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
