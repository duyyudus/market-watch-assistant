import type { AlertChannel, AlertSuppressionRule, ConfigurationPresets } from "../../../api";
import { AlertChannelsPanel } from "./settings/AlertChannelsPanel";
import { AlertSuppressionRulesPanel } from "./settings/AlertSuppressionRulesPanel";

export function AlertSettingsTab({
  channels,
  rules,
  reload,
  presets,
}: {
  channels: AlertChannel[];
  rules: AlertSuppressionRule[];
  reload: () => Promise<void>;
  presets: ConfigurationPresets | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <AlertChannelsPanel channels={channels} reload={reload} presets={presets} />
      <AlertSuppressionRulesPanel rules={rules} reload={reload} presets={presets} />
    </div>
  );
}
