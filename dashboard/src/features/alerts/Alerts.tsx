import type {
  AlertChannel,
  AlertDecision,
  AlertSuppressionRule,
  ConfigurationPresets,
  EventDetail,
} from "../../api";
import { FeatureTabs } from "../../components/FeatureTabs";
import { AlertDecisionsTab, AlertSettingsTab } from "./tabs/AlertTabs";

export type AlertTab = "decisions" | "settings";

const ALERT_TABS = [
  { id: "decisions", label: "Overview" },
  { id: "settings", label: "Settings" },
] satisfies Array<{ id: AlertTab; label: string }>;

export function Alerts({
  activeTab,
  onTabChange,
  alerts,
  alertError,
  selectedAlertId,
  selectedAlertDetail,
  selectedAlertEventDetail,
  alertDetailError,
  eventDetailError,
  retryAlerts,
  retrySelectedAlertDetail,
  acknowledge,
  dismiss,
  onSelectAlert,
  channels,
  rules,
  reload,
  presets,
}: {
  activeTab: AlertTab;
  onTabChange: (tab: AlertTab) => void;
  alerts: AlertDecision[];
  alertError?: string;
  selectedAlertId?: string;
  selectedAlertDetail?: AlertDecision;
  selectedAlertEventDetail?: EventDetail;
  alertDetailError?: string;
  eventDetailError?: string;
  retryAlerts: () => Promise<void>;
  retrySelectedAlertDetail: () => Promise<void>;
  acknowledge: (id: string) => Promise<void>;
  dismiss: (id: string) => Promise<void>;
  onSelectAlert: (id: string) => void;
  channels: AlertChannel[];
  rules: AlertSuppressionRule[];
  reload: () => Promise<void>;
  presets: ConfigurationPresets | null;
}) {
  return (
    <div className="space-y-4">
      <FeatureTabs activeTab={activeTab} onChange={onTabChange} tabs={ALERT_TABS} />

      {activeTab === "decisions" ? (
        <AlertDecisionsTab
          alerts={alerts}
          error={alertError}
          retry={retryAlerts}
          acknowledge={acknowledge}
          dismiss={dismiss}
          selectedAlertId={selectedAlertId}
          onSelectAlert={onSelectAlert}
          selectedAlertDetail={selectedAlertDetail}
          selectedAlertEventDetail={selectedAlertEventDetail}
          alertError={alertDetailError}
          eventError={eventDetailError}
          retryDetail={retrySelectedAlertDetail}
        />
      ) : (
        <AlertSettingsTab channels={channels} rules={rules} reload={reload} presets={presets} />
      )}
    </div>
  );
}
