import { Pencil, Plus, RefreshCcw, Star, Trash2, X } from "lucide-react";
import { useState } from "react";

import { api, type ConfigurationPresets, type WatchlistEntry, type WatchlistPayload } from "../../api";
import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import { useSortableData } from "../../hooks/useSortableData";
import { classNames } from "../../lib/classNames";

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
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800/40 pb-3 mb-4 text-xs text-zinc-500">
            <span>{sortedRows.length} assets watched</span>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-zinc-500">Sort by:</span>
              <SortButton
                active={sortConfig.key === "symbol"}
                direction={sortConfig.direction}
                label="Symbol"
                onClick={() => requestSort("symbol")}
              />
              <SortButton
                active={sortConfig.key === "name"}
                direction={sortConfig.direction}
                label="Name"
                onClick={() => requestSort("name")}
              />
              <SortButton
                active={sortConfig.key === "tier"}
                direction={sortConfig.direction}
                label="Tier"
                onClick={() => requestSort("tier")}
              />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {sortedRows.map((row) => {
              const label = row.symbol ?? row.name;
              return (
                <div
                  key={row.id}
                  className="rounded-md border border-zinc-800 bg-zinc-900/30 p-4 transition-all duration-150 hover:border-zinc-700/80"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-base font-bold text-zinc-100">{label}</div>
                      <div className="mt-1.5 text-sm text-base-content/75">{row.name}</div>
                    </div>
                    <Badge tone={row.enabled ? "success" : "neutral"}>{row.tier}</Badge>
                  </div>
                  <div className="mt-2.5 text-xs text-base-content/60">
                    {row.region ?? "global"} · {row.asset_class ?? row.entity_type}
                  </div>
                  {row.aliases.length > 0 ? (
                    <div className="mt-2 text-xs text-base-content/50">
                      Aliases: {row.aliases.join(", ")}
                    </div>
                  ) : null}
                  <div className="mt-4 flex gap-2">
                    <button
                      aria-label={`Edit ${label}`}
                      className="btn btn-xs btn-outline"
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
                </div>
              );
            })}
          </div>
        </>
      )}
      {deletingEntry ? (
        <div className="modal modal-visible" role="dialog" aria-modal="true">
          <div className="modal-box border border-zinc-800 bg-zinc-950">
            <h3 className="font-bold text-lg text-zinc-100">Delete watchlist entry?</h3>
            <p className="py-4 text-sm text-base-content/75">
              Are you sure you want to delete <span className="font-semibold text-zinc-200">{deletingEntry.symbol ?? deletingEntry.name}</span>? This action cannot be undone.
            </p>
            <div className="modal-action gap-2">
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => setDeletingEntry(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="btn btn-sm btn-error"
                onClick={() => void confirmDelete()}
                type="button"
              >
                Delete
              </button>
            </div>
          </div>
          <div className="modal-backdrop bg-black/60" onClick={() => setDeletingEntry(null)}></div>
        </div>
      ) : null}
    </Panel>
  );
}

function SortButton({
  active,
  direction,
  label,
  onClick,
}: {
  active: boolean;
  direction: "asc" | "desc";
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={classNames(
        "hover:text-primary transition-colors flex items-center gap-0.5",
        active && "text-primary font-semibold",
      )}
      type="button"
    >
      {label}
      {active ? (direction === "asc" ? " ▲" : " ▼") : ""}
    </button>
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
    region: form.region?.trim() || null,
    asset_class: form.asset_class?.trim() || null,
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
    <div className="mb-5 rounded-md border border-zinc-800 bg-zinc-950/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-zinc-200">
          {isNew ? "New watchlist entry" : "Edit watchlist entry"}
        </div>
        <button className="btn btn-xs btn-ghost" onClick={onCancel} type="button">
          <X className="h-4 w-4" />
          Cancel
        </button>
      </div>
      {formError ? <div className="alert alert-error mb-3 text-sm">{formError}</div> : null}
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
            onChange={(event) => update("aliases", event.target.value.split(","))}
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
    </div>
  );
}

function optionsFor(options: string[], value: string): string[] {
  return value && !options.includes(value) ? [value, ...options] : options;
}
