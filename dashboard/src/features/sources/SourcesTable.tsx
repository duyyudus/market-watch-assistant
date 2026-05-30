import { Pencil, Plus, Radio, RefreshCcw, X } from "lucide-react";
import { useState } from "react";

import { api, type ConfigurationPresets, type Source, type SourcePayload } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";

export function SourcesTable({
  rows,
  error,
  presets,
  reload,
}: {
  rows: Source[];
  error?: string;
  presets: ConfigurationPresets["sources"] | null;
  reload: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "name",
    direction: "asc",
  });
  const [editing, setEditing] = useState<Source | "new" | null>(null);
  const [form, setForm] = useState<SourcePayload>(emptySourcePayload());
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function toggle(row: Source) {
    await api.setSourceEnabled(row.id, !row.enabled);
    await reload();
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
        <div className="text-sm text-base-content/60">{sortedRows.length} configured sources</div>
        <button className="btn btn-sm btn-primary" onClick={startCreate} type="button">
          <Plus className="h-4 w-4" />
          Add source
        </button>
      </div>
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
      {error ? (
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
        <div className="overflow-x-auto">
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
      )}
    </Panel>
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
