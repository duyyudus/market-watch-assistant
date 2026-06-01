import { Send, Trash2 } from "lucide-react";
import { useState } from "react";

import type {
  AlertChannel,
  AlertChannelPayload,
  AlertSuppressionRule,
  AlertSuppressionRulePayload,
  ConfigurationPresets,
} from "../../api";
import { api } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { Panel } from "../../components/Panel";

// FALLBACK PRESETS (used when dynamic presets are not loaded yet or offline)
const FALLBACK_CHANNEL_TEMPLATES: Record<string, string> = {
  log: "{\n  \n}",
  telegram: '{\n  "chat_id": "123456789"\n}',
  webhook: '{\n  "url": "https://hooks.example.com/alerts",\n  "headers": {\n    "Authorization": "Bearer <token>"\n  }\n}'
};

const FALLBACK_CHANNEL_PLACEHOLDERS: Record<string, string> = {
  log: "e.g. Local Dev Log",
  telegram: "e.g. Core Telegram Channel",
  webhook: "e.g. Discord Webhook Alerts"
};

const FALLBACK_RULE_TEMPLATES: Record<string, string> = {
  cooldown: '{\n  "hours": 6\n}',
  quiet_hours: '{\n  "start_hour": 23,\n  "end_hour": 7,\n  "timezone": "Asia/Ho_Chi_Minh"\n}',
  region_filter: '{\n  "regions": ["us", "vietnam"],\n  "asset_classes": ["global_macro", "crypto"],\n  "weekend_only": false\n}',
  entity_mute: '{\n  "entities": ["BTC", "ETH"],\n  "until": "2026-12-31T23:59:59"\n}'
};

const FALLBACK_RULE_PLACEHOLDERS: Record<string, string> = {
  cooldown: "e.g. 6-Hour Cooldown",
  quiet_hours: "e.g. Night Quiet Hours",
  region_filter: "e.g. Focus US/VN Macro",
  entity_mute: "e.g. Mute Bitcoin Alerts"
};

function parseConfig(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  return trimmed ? (JSON.parse(trimmed) as Record<string, unknown>) : {};
}

function isValidJson(val: string): boolean {
  if (!val.trim()) return true;
  try {
    JSON.parse(val);
    return true;
  } catch {
    return false;
  }
}

// Custom structure for documentation preset items
type PresetDocItem = {
  description: string;
  parameters: Record<string, string>;
};

function getChannelPresetDoc(type: string, presets: ConfigurationPresets | null): PresetDocItem | undefined {
  const found = presets?.alerts?.channels?.find(c => c.type === type);
  if (found) {
    return {
      description: found.description,
      parameters: found.parameters
    };
  }
  
  const fallbackDocs: Record<string, PresetDocItem> = {
    log: {
      description: "Prints alerts directly to the server logs. No configuration payload is required.",
      parameters: {}
    },
    telegram: {
      description: "Dispatches alerts to a target Telegram chat or group.",
      parameters: {
        chat_id: "required: The unique chat, user, or group ID."
      }
    },
    webhook: {
      description: "Submits high-fidelity JSON payloads via HTTP POST.",
      parameters: {
        url: "required: Destination HTTP/HTTPS endpoint.",
        headers: "optional: Custom HTTP headers dictionary."
      }
    }
  };
  return fallbackDocs[type];
}

function getRulePresetDoc(type: string, presets: ConfigurationPresets | null): PresetDocItem | undefined {
  const found = presets?.alerts?.rules?.find(r => r.type === type);
  if (found) {
    return {
      description: found.description,
      parameters: found.parameters
    };
  }
  
  const fallbackDocs: Record<string, PresetDocItem> = {
    cooldown: {
      description: "Dampens frequent repetitions of the same event.",
      parameters: {
        hours: "required: Quiet interval duration before the same event triggers again."
      }
    },
    quiet_hours: {
      description: "Suspends notifications during user resting windows.",
      parameters: {
        start_hour: "required: Start hour (24-hour scale, e.g. 23).",
        end_hour: "required: End hour (24-hour scale, e.g. 7).",
        timezone: "optional: Timezone descriptor (defaults to Asia/Ho_Chi_Minh)."
      }
    },
    region_filter: {
      description: "Silences markets depending on region, category, or time.",
      parameters: {
        regions: "optional: Array of geographic scopes to mute.",
        asset_classes: "optional: Array of asset categories to mute.",
        weekend_only: "optional: Set to true to mute solely outside the weekend."
      }
    },
    entity_mute: {
      description: "Specific ticker or project silencing.",
      parameters: {
        entities: "required: Array of tickers/names (e.g. ['BTC', 'ETH']).",
        until: "optional: ISO-8601 UTC timestamp after which muting automatically ends."
      }
    }
  };
  return fallbackDocs[type];
}

function DynamicDoc({ 
  type, 
  presetItem 
}: { 
  type: string; 
  presetItem?: PresetDocItem; 
}) {
  if (!presetItem) return null;
  
  const hasParams = Object.keys(presetItem.parameters).length > 0;
  
  return (
    <div className="text-[11px] text-zinc-400 mt-1 bg-zinc-900/50 p-2.5 rounded border border-zinc-800/80 space-y-1">
      <div>
        <span className="font-semibold text-zinc-300 capitalize">{type}: </span> 
        {presetItem.description}
      </div>
      {hasParams && (
        <div className="space-y-0.5 pt-1 border-t border-zinc-800/20">
          {Object.entries(presetItem.parameters).map(([key, desc]) => (
            <div key={key}>
              • <code className="text-teal-400 bg-zinc-850 px-1 py-0.5 rounded font-mono text-[10px]">{key}</code>: {desc}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AlertControls({
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
  const channelsPresets = presets?.alerts?.channels || [];
  const rulesPresets = presets?.alerts?.rules || [];

  // Helper functions for template/placeholder lookups
  const getChannelTemplate = (type: string): string => {
    const found = channelsPresets.find(c => c.type === type);
    if (found) {
      return JSON.stringify(found.template, null, 2);
    }
    return FALLBACK_CHANNEL_TEMPLATES[type] || "{\n  \n}";
  };

  const getChannelPlaceholder = (type: string): string => {
    const found = channelsPresets.find(c => c.type === type);
    return found ? found.placeholder : (FALLBACK_CHANNEL_PLACEHOLDERS[type] || "Webhook");
  };

  const getRuleTemplate = (type: string): string => {
    const found = rulesPresets.find(r => r.type === type);
    if (found) {
      return JSON.stringify(found.template, null, 2);
    }
    return FALLBACK_RULE_TEMPLATES[type] || "{\n  \n}";
  };

  const getRulePlaceholder = (type: string): string => {
    const found = rulesPresets.find(r => r.type === type);
    return found ? found.placeholder : (FALLBACK_RULE_PLACEHOLDERS[type] || "Quiet hours");
  };

  const channelTypes = channelsPresets.length > 0
    ? channelsPresets.map(c => c.type)
    : ["log", "telegram", "webhook"];

  const ruleTypes = rulesPresets.length > 0
    ? rulesPresets.map(r => r.type)
    : ["cooldown", "quiet_hours", "region_filter", "entity_mute"];

  // States
  const [channel, setChannel] = useState<AlertChannelPayload>({
    name: "",
    channel_type: channelTypes[0] || "webhook",
    config: {},
    enabled: true,
    is_default: false,
  });
  const [channelConfig, setChannelConfig] = useState(getChannelTemplate(channelTypes[0] || "webhook"));

  const [rule, setRule] = useState<AlertSuppressionRulePayload>({
    name: "",
    rule_type: ruleTypes[0] || "cooldown",
    config: {},
    enabled: true,
  });
  const [ruleConfig, setRuleConfig] = useState(getRuleTemplate(ruleTypes[0] || "cooldown"));

  async function saveChannel() {
    await api.createAlertChannel({ ...channel, config: parseConfig(channelConfig) });
    setChannel({ ...channel, name: "" });
    setChannelConfig(getChannelTemplate(channel.channel_type));
    await reload();
  }

  async function saveRule() {
    await api.createAlertSuppressionRule({ ...rule, config: parseConfig(ruleConfig) });
    setRule({ ...rule, name: "" });
    setRuleConfig(getRuleTemplate(rule.rule_type));
    await reload();
  }

  const channelJsonValid = isValidJson(channelConfig);
  const ruleJsonValid = isValidJson(ruleConfig);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Alert channels">
        <div className="space-y-3">
          <div className="grid gap-2 md:grid-cols-[1fr_150px]">
            <input
              aria-label="Channel name"
              className="input input-bordered input-sm"
              onChange={(event) => setChannel({ ...channel, name: event.target.value })}
              placeholder={getChannelPlaceholder(channel.channel_type)}
              value={channel.name}
            />
            <select
              aria-label="Channel type"
              className="select select-bordered select-sm"
              onChange={(event) => {
                const newType = event.target.value;
                setChannel({ ...channel, channel_type: newType });
                setChannelConfig(getChannelTemplate(newType));
              }}
              value={channel.channel_type}
            >
              {channelTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>
          <div className="relative">
            <textarea
              aria-label="Channel config"
              className={`textarea textarea-bordered min-h-28 w-full font-mono text-xs p-3 ${
                !channelJsonValid ? "textarea-error border-red-500 focus:border-red-500" : ""
              }`}
              onChange={(event) => setChannelConfig(event.target.value)}
              value={channelConfig}
            />
            {!channelJsonValid && (
              <span className="text-[10px] text-red-500 absolute bottom-3 right-3 px-1.5 py-0.5 rounded bg-black/80 font-semibold border border-red-500/30">
                Invalid JSON
              </span>
            )}
          </div>
          <DynamicDoc type={channel.channel_type} presetItem={getChannelPresetDoc(channel.channel_type, presets)} />
          <button
            className="btn btn-sm btn-primary w-full md:w-auto mt-1"
            disabled={!channelJsonValid || !channel.name.trim()}
            onClick={() => void saveChannel()}
            type="button"
          >
            Save channel
          </button>
          {channels.length === 0 ? (
            <EmptyState title="No alert channels" body="Delivery channels appear here." />
          ) : (
            <div className="divide-y divide-zinc-800 mt-2">
              {channels.map((item) => (
                <div className="flex items-center justify-between gap-3 py-2.5" key={item.id}>
                  <div>
                    <div className="text-sm font-semibold">{item.name}</div>
                    <div className="text-xs text-zinc-500">{item.channel_type}</div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      aria-label={`test ${item.name}`}
                      className="btn btn-xs btn-outline"
                      onClick={() => void api.testAlertChannel(item.id, "Dashboard test alert")}
                      type="button"
                    >
                      <Send className="h-3.5 w-3.5" />
                    </button>
                    <button
                      aria-label={`delete ${item.name}`}
                      className="btn btn-xs btn-outline"
                      onClick={() => void api.deleteAlertChannel(item.id).then(reload)}
                      type="button"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Panel>
      <Panel title="Suppression rules">
        <div className="space-y-3">
          <div className="grid gap-2 md:grid-cols-[1fr_170px]">
            <input
              aria-label="Rule name"
              className="input input-bordered input-sm"
              onChange={(event) => setRule({ ...rule, name: event.target.value })}
              placeholder={getRulePlaceholder(rule.rule_type)}
              value={rule.name}
            />
            <select
              aria-label="Rule type"
              className="select select-bordered select-sm"
              onChange={(event) => {
                const newType = event.target.value;
                setRule({ ...rule, rule_type: newType });
                setRuleConfig(getRuleTemplate(newType));
              }}
              value={rule.rule_type}
            >
              {ruleTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>
          <div className="relative">
            <textarea
              aria-label="Rule config"
              className={`textarea textarea-bordered min-h-28 w-full font-mono text-xs p-3 ${
                !ruleJsonValid ? "textarea-error border-red-500 focus:border-red-500" : ""
              }`}
              onChange={(event) => setRuleConfig(event.target.value)}
              value={ruleConfig}
            />
            {!ruleJsonValid && (
              <span className="text-[10px] text-red-500 absolute bottom-3 right-3 px-1.5 py-0.5 rounded bg-black/80 font-semibold border border-red-500/30">
                Invalid JSON
              </span>
            )}
          </div>
          <DynamicDoc type={rule.rule_type} presetItem={getRulePresetDoc(rule.rule_type, presets)} />
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
    </div>
  );
}
