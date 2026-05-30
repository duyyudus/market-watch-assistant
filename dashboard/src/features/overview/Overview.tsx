import { Panel } from "../../components/Panel";
import { AlertsTable } from "../../features/alerts/AlertsTable";
import { EventRows } from "../../features/events/EventRows";
import type { DashboardState, ResourceErrors } from "../../types/dashboard";

export function Overview({
  state,
  errors,
  retry,
}: {
  state: DashboardState;
  errors: ResourceErrors;
  retry: () => Promise<void>;
}) {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Priority events">
          <EventRows events={state.events.slice(0, 8)} error={errors.events} retry={retry} />
        </Panel>
        <Panel title="Recent alerts">
          <AlertsTable rows={state.alerts.slice(0, 5)} compact error={errors.alerts} retry={retry} />
        </Panel>
      </div>
    </div>
  );
}

