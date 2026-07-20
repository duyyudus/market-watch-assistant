import { Pencil, Plus, RefreshCcw, Star, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, type ConfigurationPresets, type WatchlistEntry, type WatchlistPayload } from "../../api";
import { Badge } from "../../components/Badge";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { InlineEditPanel } from "../../components/InlineEditPanel";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { SortableHeader } from "../../components/SortableHeader";
import { useSortableData } from "../../hooks/useSortableData";

export function WatchlistTable({
  rows,
  error,
  presets,
  retry,
}: {
  rows: WatchlistEntry[];
  error?: string;
  presets: ConfigurationPresets["watchlist"] | null;
  retry: () => Promise<void>;
}) {
  const { items: sortedRows, requestSort, sortConfig } = useSortableData(rows, {
    key: "symbol",
    direction: "asc",
  });
  const [editing, setEditing] = useState<WatchlistEntry | "new" | null>(null);
  const [form, setForm] = useState<WatchlistPayload>(emptyWatchlistPayload(presets));
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingEntry, setDeletingEntry] = useState<WatchlistEntry | null>(null);

  function startCreate() {
    setEditing("new");
    setForm(emptyWatchlistPayload(presets));
    setFormError(null);
  }

  function startEdit(row: WatchlistEntry) {
    setEditing(row);
    setForm({
      symbol: row.symbol ?? "",
      name: row.name,
      entity_type: row.entity_type,
      tier: row.tier,
      region: row.region ?? "",
      asset_class: row.asset_class ?? "",
      aliases: row.aliases,
      enabled: row.enabled,
    });
    setFormError(null);
  }

  async function saveEntry() {
    setSaving(true);
    setFormError(null);
    try {
      if (editing === "new") {
        await api.createWatchlistEntry(normalizePayload(form));
      } else if (editing) {
        await api.updateWatchlistEntry(editing.id, normalizePayload(form));
      }
      setEditing(null);
      await retry();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to save watchlist entry");
    } finally {
      setSaving(false);
    }
  }
  async function confirmDelete() {
    if (!deletingEntry) return;
    try {
      await api.deleteWatchlistEntry(deletingEntry.id);
      setDeletingEntry(null);
      await retry();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Unable to delete watchlist entry");
    }
  }

  return (
    <Panel title="Watchlist">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-base-content/60">{sortedRows.length} assets watched</div>
        <button className="btn btn-sm btn-primary" onClick={startCreate} type="button">
          <Plus className="h-4 w-4" />
          Add watchlist entry
        </button>
      </div>
      {editing ? (
        <WatchlistForm
          form={form}
          formError={formError}
          isNew={editing === "new"}
          presets={presets}
          saving={saving}
          setForm={setForm}
          onCancel={() => setEditing(null)}
          onSave={saveEntry}
        />
      ) : null}
      {error ? (
        <SectionError title="Watchlist unavailable" message={error} retry={retry} />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={Star}
          title="No watchlist entries yet"
          body="Tracked assets and entities will appear here after they are added."
          action={
            <button className="btn btn-sm btn-outline" onClick={() => void retry()} type="button">
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </button>
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="table w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
                <SortableHeader
                  label="Symbol"
                  sortKey="symbol"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Name"
                  sortKey="name"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Entity type"
                  sortKey="entity_type"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <SortableHeader
                  label="Tier"
                  sortKey="tier"
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
                  label="Asset class"
                  sortKey="asset_class"
                  currentSortKey={sortConfig.key}
                  direction={sortConfig.direction}
                  onSort={requestSort}
                />
                <th className="px-4 py-3 text-left">Aliases</th>
                <th className="px-4 py-3 text-left">Enabled</th>
                <th className="px-4 py-3 text-left">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {sortedRows.map((row) => {
                const label = row.symbol ?? row.name;
                return (
                  <tr key={row.id} className="border-b border-zinc-800/30">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-bold text-zinc-100">
                      {row.symbol ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-300">
                      {row.name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-400">
                      {row.entity_type}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <Badge tone="neutral">{row.tier}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-400">
                      {row.region ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-zinc-400">
                      {row.asset_class ?? "—"}
                    </td>
                    <td className="max-w-64 px-4 py-3 text-xs text-zinc-400">
                      {row.aliases.length > 0 ? row.aliases.join(", ") : "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <Badge tone={row.enabled ? "success" : "neutral"}>
                        {row.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex gap-2">
                        <button
                          aria-label={`Edit ${label}`}
                          className="btn btn-xs btn-outline btn-primary"
                          onClick={() => startEdit(row)}
                          type="button"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                          Edit
                        </button>
                        <button
                          aria-label={`Delete ${label}`}
                          className="btn btn-xs btn-ghost text-error"
                          onClick={() => setDeletingEntry(row)}
                          type="button"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog
        confirmLabel="Delete"
        open={Boolean(deletingEntry)}
        title="Delete watchlist entry?"
        description={`Are you sure you want to delete ${
          deletingEntry?.symbol ?? deletingEntry?.name ?? "this watchlist entry"
        }? This action cannot be undone.`}
        onCancel={() => setDeletingEntry(null)}
        onConfirm={() => void confirmDelete()}
      />
    </Panel>
  );
}

function emptyWatchlistPayload(
  presets?: ConfigurationPresets["watchlist"] | null,
): WatchlistPayload {
  return {
    symbol: "",
    name: "",
    entity_type: presets?.entity_types[0] ?? "",
    tier: presets?.tiers[presets.tiers.length - 1] ?? "",
    region: presets?.regions[0] ?? "",
    asset_class: presets?.asset_classes[0] ?? "",
    aliases: [],
    enabled: true,
  };
}

function normalizePayload(form: WatchlistPayload): WatchlistPayload {
  return {
    ...form,
    symbol: form.symbol?.trim() || null,
    // region/asset_class are required; keep them as strings so a blank value is
    // rejected by the API instead of being coerced to null and nulling the column.
    region: form.region?.trim() ?? "",
    asset_class: form.asset_class?.trim() ?? "",
    tier: form.tier.toUpperCase(),
    aliases: form.aliases.map((alias) => alias.trim()).filter(Boolean),
  };
}

function WatchlistForm({
  form,
  formError,
  isNew,
  presets,
  saving,
  setForm,
  onCancel,
  onSave,
}: {
  form: WatchlistPayload;
  formError: string | null;
  isNew: boolean;
  presets: ConfigurationPresets["watchlist"] | null;
  saving: boolean;
  setForm: (value: WatchlistPayload) => void;
  onCancel: () => void;
  onSave: () => Promise<void>;
}) {
  function update<K extends keyof WatchlistPayload>(key: K, value: WatchlistPayload[K]) {
    setForm({ ...form, [key]: value });
  }

  return (
    <InlineEditPanel
      title={isNew ? "New watchlist entry" : "Edit watchlist entry"}
      error={formError}
      onCancel={onCancel}
    >
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label className="form-control">
          <span className="label-text">Symbol</span>
          <input
            className="input input-bordered input-sm"
            onChange={(event) => update("symbol", event.target.value)}
            value={form.symbol ?? ""}
          />
        </label>
        <label className="form-control">
          <span className="label-text">Entity name</span>
          <input
            className="input input-bordered input-sm"
            onChange={(event) => update("name", event.target.value)}
            value={form.name}
          />
        </label>
        <label className="form-control">
          <span className="label-text">Entity type</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("entity_type", event.target.value)}
            value={form.entity_type}
          >
            {optionsFor(presets?.entity_types ?? [], form.entity_type).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Tier</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("tier", event.target.value)}
            value={form.tier}
          >
            {optionsFor(presets?.tiers ?? [], form.tier).map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Region</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("region", event.target.value)}
            value={form.region ?? ""}
          >
            {optionsFor(presets?.regions ?? [], form.region ?? "").map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control">
          <span className="label-text">Asset class</span>
          <select
            className="select select-bordered select-sm"
            onChange={(event) => update("asset_class", event.target.value)}
            value={form.asset_class ?? ""}
          >
            {optionsFor(presets?.asset_classes ?? [], form.asset_class ?? "").map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="form-control md:col-span-2">
          <span className="label-text">Aliases</span>
          <input
            className="input input-bordered input-sm"
            onChange={(event) =>
              update(
                "aliases",
                event.target.value.split(",").map((alias) => alias.trim()),
              )
            }
            value={form.aliases.join(", ")}
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
          Save watchlist entry
        </button>
      </div>
    </InlineEditPanel>
  );
}

function optionsFor(options: string[], value: string): string[] {
  return value && !options.includes(value) ? [value, ...options] : options;
}
