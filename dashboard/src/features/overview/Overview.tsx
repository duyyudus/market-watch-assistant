import { Bell, Play } from "lucide-react";

import { Metric } from "../../components/Metric";
import { Panel } from "../../components/Panel";
import { AlertsTable } from "../../features/alerts/AlertsTable";
import { CommandsTable } from "../../features/commands/CommandsTable";
import { EventRows } from "../../features/events/EventRows";
import { JobsTable } from "../../features/operations/JobsTable";
import type { DashboardState, QueueCommand, ResourceErrors } from "../../types/dashboard";

export function Overview({
  state,
  errors,
  queue,
  retry,
}: {
  state: DashboardState;
  errors: ResourceErrors;
  queue: QueueCommand;
  retry: () => Promise<void>;
}) {
  const enabledSources = state.sources.filter((source) => source.enabled).length;
  const immediateAlerts = state.alerts.filter((alert) => alert.decision === "immediate_alert").length;
  const failedJobs = state.jobs.filter((job) => job.status !== "success").length;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric
          label="High score events"
          value={state.events.filter((event) => event.final_score >= 80).length}
        />
        <Metric label="Enabled sources" value={`${enabledSources}/${state.sources.length}`} />
        <Metric label="Immediate alerts" value={immediateAlerts} />
        <Metric label="Job failures" value={failedJobs} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Priority events">
          <EventRows events={state.events.slice(0, 8)} error={errors.events} retry={retry} />
        </Panel>
        <Panel title="Manual controls">
          <div className="grid gap-2">
            <button
              className="btn btn-primary btn-sm justify-start"
              onClick={() => queue("pipeline.run", { dry_run: true })}
              type="button"
            >
              <Play className="h-4 w-4" />
              Dry-run pipeline
            </button>
            <button
              className="btn btn-outline btn-sm justify-start"
              onClick={() =>
                queue("alert.dispatch", { channel: "telegram", limit: 20, dry_run: true })
              }
              type="button"
            >
              <Bell className="h-4 w-4" />
              Preview alert dispatch
            </button>
          </div>
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Recent alerts">
          <AlertsTable rows={state.alerts.slice(0, 5)} compact error={errors.alerts} retry={retry} />
        </Panel>
        <Panel title="Recent jobs">
          <JobsTable rows={state.jobs.slice(0, 6)} error={errors.jobs} retry={retry} />
        </Panel>
        <Panel title="Command queue">
          <CommandsTable
            rows={state.commands.slice(0, 6)}
            compact
            error={errors.commands}
            retry={retry}
            queue={queue}
          />
        </Panel>
      </div>
    </div>
  );
}

