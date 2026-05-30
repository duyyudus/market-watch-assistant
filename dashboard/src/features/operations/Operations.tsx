import { useEffect, useState } from "react";

import { api, type AlertDecision, type AlertPolicy } from "../../api";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import type { QueueCommand, ResourceErrors } from "../../types/dashboard";
import { JobsTable } from "./JobsTable";
import type { JobRun } from "../../api";

export function Operations({
  jobs,
  alerts,
  errors,
  alertPolicy,
  queue,
  retry,
}: {
  jobs: JobRun[];
  alerts: AlertDecision[];
  errors: ResourceErrors;
  alertPolicy: AlertPolicy | null;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Job history">
        <JobsTable rows={jobs} error={errors.jobs} retry={retry} />
      </Panel>
      <Panel title="Alert policy">
        <AlertPolicyForm policy={alertPolicy} error={errors.alertPolicy} retry={retry} />
      </Panel>
      <Panel title="Alert operations">
        {errors.alerts ? (
          <SectionError title="Alert operations unavailable" message={errors.alerts} retry={retry} />
        ) : (
          <div className="space-y-2">
            <button
              className="btn btn-sm btn-outline w-full justify-start"
              onClick={() =>
                queue("alert.dispatch", { channel: "telegram", limit: 20, dry_run: true })
              }
              type="button"
            >
              Dry-run dispatch
            </button>
            <div className="text-sm text-base-content/60">{alerts.length} recent alert decisions</div>
          </div>
        )}
      </Panel>
    </div>
  );
}


function AlertPolicyForm({
  policy,
  error,
  retry,
}: {
  policy: AlertPolicy | null;
  error?: string;
  retry: () => Promise<void>;
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
      await retry();
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Unable to save alert policy");
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return <SectionError title="Alert policy unavailable" message={error} retry={retry} />;
  }

  return (
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
