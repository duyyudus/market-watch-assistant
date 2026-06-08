import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import type {
  AlertSuppressionRule,
  AlertSuppressionRulePayload,
  ConfigurationPresets,
} from "../../../../api";
import { api } from "../../../../api";
import { EmptyState } from "../../../../components/EmptyState";
import { Panel } from "../../../../components/Panel";
import {
  AlertPresetDoc,
  JsonConfigField,
  type AlertPresetDocItem,
} from "./AlertConfigFields";

const FALLBACK_RULE_TEMPLATES: Record<string, string> = {
  cooldown: '{\n  "hours": 6\n}',
  quiet_hours: '{\n  "start_hour": 23,\n  "end_hour": 7,\n  "timezone": "Asia/Ho_Chi_Minh"\n}',
  region_filter:
    '{\n  "regions": ["us", "vietnam"],\n  "asset_classes": ["global_macro", "crypto"],\n  "weekend_only": false\n}',
  entity_mute: '{\n  "entities": ["BTC", "ETH"],\n  "until": "2026-12-31T23:59:59"\n}',
};

const FALLBACK_RULE_PLACEHOLDERS: Record<string, string> = {
  cooldown: "e.g. 6-Hour Cooldown",
  quiet_hours: "e.g. Night Quiet Hours",
  region_filter: "e.g. Focus US/VN Macro",
  entity_mute: "e.g. Mute Bitcoin Alerts",
};

export function AlertSuppressionRulesPanel({
  rules,
  reload,
  presets,
}: {
  rules: AlertSuppressionRule[];
  reload: () => Promise<void>;
  presets: ConfigurationPresets | null;
}) {
  const rulePresets = presets?.alerts?.rules || [];
  const ruleTypes = rulePresets.length
    ? rulePresets.map((rule) => rule.type)
    : ["cooldown", "quiet_hours", "region_filter", "entity_mute"];

  const [rule, setRule] = useState<AlertSuppressionRulePayload>({
    name: "",
    rule_type: ruleTypes[0] || "cooldown",
    config: {},
    enabled: true,
  });
  const [ruleConfig, setRuleConfig] = useState(
    getRuleTemplate(ruleTypes[0] || "cooldown", presets),
  );

  useEffect(() => {
    if (!presets || rule.name) return;
    const firstRuleType = ruleTypes[0] || "cooldown";
    setRule((current) => ({ ...current, rule_type: firstRuleType }));
    setRuleConfig(getRuleTemplate(firstRuleType, presets));
  }, [presets]);

  async function saveRule() {
    await api.createAlertSuppressionRule({ ...rule, config: parseConfig(ruleConfig) });
    setRule({ ...rule, name: "" });
    setRuleConfig(getRuleTemplate(rule.rule_type, presets));
    await reload();
  }

  const ruleJsonValid = isValidJson(ruleConfig);

  return (
    <Panel title="Suppression rules">
      <div className="space-y-3">
        <div className="grid gap-2 md:grid-cols-[1fr_170px]">
          <input
            aria-label="Rule name"
            className="input input-bordered input-sm"
            onChange={(event) => setRule({ ...rule, name: event.target.value })}
            placeholder={getRulePlaceholder(rule.rule_type, presets)}
            value={rule.name}
          />
          <select
            aria-label="Rule type"
            className="select select-bordered select-sm"
            onChange={(event) => {
              const newType = event.target.value;
              setRule({ ...rule, rule_type: newType });
              setRuleConfig(getRuleTemplate(newType, presets));
            }}
            value={rule.rule_type}
          >
            {ruleTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <JsonConfigField
          label="Rule config"
          value={ruleConfig}
          valid={ruleJsonValid}
          onChange={setRuleConfig}
        />
        <AlertPresetDoc
          type={rule.rule_type}
          presetItem={getRulePresetDoc(rule.rule_type, presets)}
        />
        <button
          className="btn btn-sm btn-primary w-full md:w-auto mt-1"
          disabled={!ruleJsonValid || !rule.name.trim()}
          onClick={() => void saveRule()}
          type="button"
        >
          Save suppression rule
        </button>
        {rules.length === 0 ? (
          <EmptyState title="No suppression rules" body="Suppression rules appear here." />
        ) : (
          <div className="divide-y divide-zinc-800 mt-2">
            {rules.map((item) => (
              <div className="flex items-center justify-between gap-3 py-2.5" key={item.id}>
                <div>
                  <div className="text-sm font-semibold">{item.name}</div>
                  <div className="text-xs text-zinc-500">{item.rule_type}</div>
                </div>
                <button
                  aria-label={`delete ${item.name}`}
                  className="btn btn-xs btn-outline"
                  onClick={() => void api.deleteAlertSuppressionRule(item.id).then(reload)}
                  type="button"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

function getRuleTemplate(type: string, presets: ConfigurationPresets | null): string {
  const found = presets?.alerts?.rules?.find((rule) => rule.type === type);
  if (found) {
    return JSON.stringify(found.template, null, 2);
  }
  return FALLBACK_RULE_TEMPLATES[type] || "{\n  \n}";
}

function getRulePlaceholder(type: string, presets: ConfigurationPresets | null): string {
  const found = presets?.alerts?.rules?.find((rule) => rule.type === type);
  return found ? found.placeholder : FALLBACK_RULE_PLACEHOLDERS[type] || "Quiet hours";
}

function getRulePresetDoc(
  type: string,
  presets: ConfigurationPresets | null,
): AlertPresetDocItem | undefined {
  const found = presets?.alerts?.rules?.find((rule) => rule.type === type);
  if (found) {
    return {
      description: found.description,
      parameters: found.parameters,
    };
  }

  const fallbackDocs: Record<string, AlertPresetDocItem> = {
    cooldown: {
      description: "Dampens frequent repetitions of the same event.",
      parameters: {
        hours: "required: Quiet interval duration before the same event triggers again.",
      },
    },
    quiet_hours: {
      description: "Suspends notifications during user resting windows.",
      parameters: {
        start_hour: "required: Start hour (24-hour scale, e.g. 23).",
        end_hour: "required: End hour (24-hour scale, e.g. 7).",
        timezone: "optional: Timezone descriptor (defaults to Asia/Ho_Chi_Minh).",
      },
    },
    region_filter: {
      description: "Silences markets depending on region, category, or time.",
      parameters: {
        regions: "optional: Array of geographic scopes to mute.",
        asset_classes: "optional: Array of asset categories to mute.",
        weekend_only: "optional: Set to true to mute solely outside the weekend.",
      },
    },
    entity_mute: {
      description: "Specific ticker or project silencing.",
      parameters: {
        entities: "required: Array of tickers/names (e.g. ['BTC', 'ETH']).",
        until: "optional: ISO-8601 UTC timestamp after which muting automatically ends.",
      },
    },
  };
  return fallbackDocs[type];
}

function parseConfig(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  return trimmed ? (JSON.parse(trimmed) as Record<string, unknown>) : {};
}

function isValidJson(value: string): boolean {
  if (!value.trim()) return true;
  try {
    JSON.parse(value);
    return true;
  } catch {
    return false;
  }
}
