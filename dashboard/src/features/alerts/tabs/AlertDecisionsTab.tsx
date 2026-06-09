import type { AlertDecision, EventDetail } from "../../../api";
import { Panel } from "../../../components/Panel";
import { AlertsTable } from "../AlertsTable";
import { AlertDetailPanel } from "./AlertDetailPanel";

export function AlertDecisionsTab({
  alerts,
  error,
  selectedAlertId,
  selectedAlertDetail,
  selectedAlertEventDetail,
  alertError,
  eventError,
  retry,
  retryDetail,
  acknowledge,
  dismiss,
  onSelectAlert,
}: {
  alerts: AlertDecision[];
  error?: string;
  selectedAlertId?: string;
  selectedAlertDetail?: AlertDecision;
  selectedAlertEventDetail?: EventDetail;
  alertError?: string;
  eventError?: string;
  retry: () => Promise<void>;
  retryDetail: () => Promise<void>;
  acknowledge: (id: string) => Promise<void>;
  dismiss: (id: string) => Promise<void>;
  onSelectAlert: (id: string) => void;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
      <Panel title="Alert decisions">
        <AlertsTable
          rows={alerts}
          error={error}
          retry={retry}
          acknowledge={acknowledge}
          dismiss={dismiss}
          selectedAlertId={selectedAlertId}
          onSelectAlert={onSelectAlert}
        />
      </Panel>
      <Panel title="Alert detail">
        <AlertDetailPanel
          alert={selectedAlertDetail}
          eventDetail={selectedAlertEventDetail}
          alertError={alertError}
          eventError={eventError}
          retry={retryDetail}
        />
      </Panel>
    </div>
  );
}
