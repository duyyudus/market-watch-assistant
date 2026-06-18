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
  maxItems,
  decision,
  offset,
  pageSize,
  total,
  setMaxItems,
  setDecision,
  setOffset,
  selectedAlertId,
  selectedAlertDetail,
  selectedAlertEventDetail,
  alertDetailError,
  eventDetailError,
  retryAlerts,
  retrySelectedAlertDetail,
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
  maxItems: number | null;
  decision: string | null;
  offset: number;
  pageSize: number;
  total: number;
  setMaxItems: (value: number | null) => void;
  setDecision: (value: string | null) => void;
  setOffset: (value: number) => void;
  selectedAlertId?: string;
  selectedAlertDetail?: AlertDecision;
  selectedAlertEventDetail?: EventDetail;
  alertDetailError?: string;
  eventDetailError?: string;
  retryAlerts: () => Promise<void>;
  retrySelectedAlertDetail: () => Promise<void>;
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
          maxItems={maxItems}
          decision={decision}
          offset={offset}
          pageSize={pageSize}
          total={total}
          setMaxItems={setMaxItems}
          setDecision={setDecision}
          setOffset={setOffset}
          retry={retryAlerts}
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
