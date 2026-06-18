import type { AlertDecision } from "../../api";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import type { QueueCommand, ResourceErrors } from "../../types/dashboard";
import { JobsTable } from "./JobsTable";
import type { JobRun } from "../../api";

export function Operations({
  jobs,
  alerts,
  errors,
  queue,
  retry,
}: {
  jobs: JobRun[];
  alerts: AlertDecision[];
  errors: ResourceErrors;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Job history">
        <JobsTable rows={jobs} error={errors.jobs} retry={retry} />
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
