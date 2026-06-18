import type {
  AlertChannel,
  AlertPolicy,
  AlertSuppressionRule,
  ConfigurationPresets,
} from "../../../api";
import { AlertChannelsPanel } from "./settings/AlertChannelsPanel";
import { AlertPolicyPanel } from "./settings/AlertPolicyPanel";
import { AlertSuppressionRulesPanel } from "./settings/AlertSuppressionRulesPanel";

export function AlertSettingsTab({
  alertPolicy,
  alertPolicyError,
  channels,
  rules,
  reload,
  presets,
}: {
  alertPolicy: AlertPolicy | null;
  alertPolicyError?: string;
  channels: AlertChannel[];
  rules: AlertSuppressionRule[];
  reload: () => Promise<void>;
  presets: ConfigurationPresets | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <AlertPolicyPanel policy={alertPolicy} error={alertPolicyError} reload={reload} />
      <AlertChannelsPanel channels={channels} reload={reload} presets={presets} />
      <AlertSuppressionRulesPanel rules={rules} reload={reload} presets={presets} />
    </div>
  );
}
