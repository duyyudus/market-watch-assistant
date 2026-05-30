import { Radio } from "lucide-react";

import type { AlertDecision, Source } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";
import { SectionError } from "../../components/SectionError";
import type { QueueCommand, ResourceErrors } from "../../types/dashboard";
import { JobsTable } from "./JobsTable";
import type { JobRun } from "../../api";

export function Operations({
  jobs,
  alerts,
  sources,
  errors,
  queue,
  retry,
}: {
  jobs: JobRun[];
  alerts: AlertDecision[];
  sources: Source[];
  errors: ResourceErrors;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
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
      <Panel title="Source actions">
        {errors.sources ? (
          <SectionError title="Source actions unavailable" message={errors.sources} retry={retry} />
        ) : sources.length === 0 ? (
          <EmptyState
            icon={Radio}
            title="No source actions available"
            body="Fetch controls appear after sources are configured."
          />
        ) : (
          <div className="space-y-2">
            {sources.slice(0, 6).map((source) => (
              <button
                key={source.id}
                className="btn btn-sm btn-ghost w-full justify-between text-sm"
                onClick={() => queue("source.fetch", { source_id: source.id })}
                type="button"
              >
                <span>{source.name}</span>
                <Radio className="h-4 w-4" />
              </button>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

