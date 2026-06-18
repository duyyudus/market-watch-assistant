import { useEffect, useState } from "react";

import { api, type AlertPolicy } from "../../../../api";
import { Panel } from "../../../../components/Panel";
import { SectionError } from "../../../../components/SectionError";

export function AlertPolicyPanel({
  policy,
  error,
  reload,
}: {
  policy: AlertPolicy | null;
  error?: string;
  reload: () => Promise<void>;
}) {
  const [form, setForm] = useState<AlertPolicy>(policy ?? defaultPolicy());
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (policy) setForm(policy);
  }, [policy]);

  async function savePolicy() {
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateAlertPolicy(form);
      await reload();
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Unable to save alert policy");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Alert policy">
      {error ? (
        <SectionError title="Alert policy unavailable" message={error} retry={reload} />
      ) : (
        <div className="space-y-3">
          {saveError ? <div className="alert alert-error text-sm">{saveError}</div> : null}
          <label className="form-control">
            <span className="label-text">Immediate threshold</span>
            <input
              className="input input-bordered input-sm"
              max={100}
              min={0}
              onChange={(event) =>
                setForm({ ...form, immediate_threshold: Number(event.target.value) })
              }
              type="number"
              value={form.immediate_threshold}
            />
          </label>
          <label className="form-control">
            <span className="label-text">Watchlist threshold</span>
            <input
              className="input input-bordered input-sm"
              max={100}
              min={0}
              onChange={(event) =>
                setForm({ ...form, watchlist_threshold: Number(event.target.value) })
              }
              type="number"
              value={form.watchlist_threshold}
            />
          </label>
          <label className="form-control">
            <span className="label-text">Digest threshold</span>
            <input
              className="input input-bordered input-sm"
              max={100}
              min={0}
              onChange={(event) => setForm({ ...form, digest_threshold: Number(event.target.value) })}
              type="number"
              value={form.digest_threshold}
            />
          </label>
          <label className="form-control">
            <span className="label-text">Default channel</span>
            <input
              className="input input-bordered input-sm"
              onChange={(event) => setForm({ ...form, default_channel: event.target.value })}
              value={form.default_channel}
            />
          </label>
          <button
            className="btn btn-sm btn-primary w-full"
            disabled={saving}
            onClick={() => void savePolicy()}
            type="button"
          >
            Save alert policy
          </button>
        </div>
      )}
    </Panel>
  );
}

function defaultPolicy(): AlertPolicy {
  return {
    immediate_threshold: 80,
    watchlist_threshold: 55,
    digest_threshold: 30,
    default_channel: "log",
  };
}
