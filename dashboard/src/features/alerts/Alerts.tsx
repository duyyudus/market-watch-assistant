import type {
  AlertChannel,
  AlertDecision,
  AlertPolicy,
  AlertSuppressionRule,
  ConfigurationPresets,
  EventDetail,
  NewsDetail,
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
  newsDetails,
  alertDetailError,
  eventDetailError,
  newsDetailError,
  retryAlerts,
  retrySelectedAlertDetail,
  loadNewsDetail,
  onSelectAlert,
  alertPolicy,
  alertPolicyError,
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
  newsDetails: Record<string, NewsDetail>;
  alertDetailError?: string;
  eventDetailError?: string;
  newsDetailError?: string;
  retryAlerts: () => Promise<void>;
  retrySelectedAlertDetail: () => Promise<void>;
  loadNewsDetail: (id: string) => void;
  onSelectAlert: (id: string) => void;
  alertPolicy: AlertPolicy | null;
  alertPolicyError?: string;
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
          newsDetails={newsDetails}
          alertError={alertDetailError}
          eventError={eventDetailError}
          newsDetailError={newsDetailError}
          retryDetail={retrySelectedAlertDetail}
          loadNewsDetail={loadNewsDetail}
        />
      ) : (
        <AlertSettingsTab
          alertPolicy={alertPolicy}
          alertPolicyError={alertPolicyError}
          channels={channels}
          rules={rules}
          reload={reload}
          presets={presets}
        />
      )}
    </div>
  );
}
