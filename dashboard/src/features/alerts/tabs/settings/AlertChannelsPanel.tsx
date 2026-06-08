import { Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import type { AlertChannel, AlertChannelPayload, ConfigurationPresets } from "../../../../api";
import { api } from "../../../../api";
import { EmptyState } from "../../../../components/EmptyState";
import { Panel } from "../../../../components/Panel";
import {
  AlertPresetDoc,
  JsonConfigField,
  type AlertPresetDocItem,
} from "./AlertConfigFields";

const FALLBACK_CHANNEL_TEMPLATES: Record<string, string> = {
  log: "{\n  \n}",
  telegram: '{\n  "chat_id": "123456789"\n}',
  webhook:
    '{\n  "url": "https://hooks.example.com/alerts",\n  "headers": {\n    "Authorization": "Bearer <token>"\n  }\n}',
};

const FALLBACK_CHANNEL_PLACEHOLDERS: Record<string, string> = {
  log: "e.g. Local Dev Log",
  telegram: "e.g. Core Telegram Channel",
  webhook: "e.g. Discord Webhook Alerts",
};

export function AlertChannelsPanel({
  channels,
  reload,
  presets,
}: {
  channels: AlertChannel[];
  reload: () => Promise<void>;
  presets: ConfigurationPresets | null;
}) {
  const channelPresets = presets?.alerts?.channels || [];
  const channelTypes = channelPresets.length
    ? channelPresets.map((channel) => channel.type)
    : ["log", "telegram", "webhook"];

  const [channel, setChannel] = useState<AlertChannelPayload>({
    name: "",
    channel_type: channelTypes[0] || "webhook",
    config: {},
    enabled: true,
    is_default: false,
  });
  const [channelConfig, setChannelConfig] = useState(
    getChannelTemplate(channelTypes[0] || "webhook", presets),
  );

  useEffect(() => {
    if (!presets || channel.name) return;
    const firstChannelType = channelTypes[0] || "webhook";
    setChannel((current) => ({ ...current, channel_type: firstChannelType }));
    setChannelConfig(getChannelTemplate(firstChannelType, presets));
  }, [presets]);

  async function saveChannel() {
    await api.createAlertChannel({ ...channel, config: parseConfig(channelConfig) });
    setChannel({ ...channel, name: "" });
    setChannelConfig(getChannelTemplate(channel.channel_type, presets));
    await reload();
  }

  const channelJsonValid = isValidJson(channelConfig);

  return (
    <Panel title="Alert channels">
      <div className="space-y-3">
        <div className="grid gap-2 md:grid-cols-[1fr_150px]">
          <input
            aria-label="Channel name"
            className="input input-bordered input-sm"
            onChange={(event) => setChannel({ ...channel, name: event.target.value })}
            placeholder={getChannelPlaceholder(channel.channel_type, presets)}
            value={channel.name}
          />
          <select
            aria-label="Channel type"
            className="select select-bordered select-sm"
            onChange={(event) => {
              const newType = event.target.value;
              setChannel({ ...channel, channel_type: newType });
              setChannelConfig(getChannelTemplate(newType, presets));
            }}
            value={channel.channel_type}
          >
            {channelTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <JsonConfigField
          label="Channel config"
          value={channelConfig}
          valid={channelJsonValid}
          onChange={setChannelConfig}
        />
        <AlertPresetDoc
          type={channel.channel_type}
          presetItem={getChannelPresetDoc(channel.channel_type, presets)}
        />
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
  );
}

function getChannelTemplate(type: string, presets: ConfigurationPresets | null): string {
  const found = presets?.alerts?.channels?.find((channel) => channel.type === type);
  if (found) {
    return JSON.stringify(found.template, null, 2);
  }
  return FALLBACK_CHANNEL_TEMPLATES[type] || "{\n  \n}";
}

function getChannelPlaceholder(type: string, presets: ConfigurationPresets | null): string {
  const found = presets?.alerts?.channels?.find((channel) => channel.type === type);
  return found ? found.placeholder : FALLBACK_CHANNEL_PLACEHOLDERS[type] || "Webhook";
}

function getChannelPresetDoc(
  type: string,
  presets: ConfigurationPresets | null,
): AlertPresetDocItem | undefined {
  const found = presets?.alerts?.channels?.find((channel) => channel.type === type);
  if (found) {
    return {
      description: found.description,
      parameters: found.parameters,
    };
  }

  const fallbackDocs: Record<string, AlertPresetDocItem> = {
    log: {
      description: "Prints alerts directly to the server logs. No configuration payload is required.",
      parameters: {},
    },
    telegram: {
      description: "Dispatches alerts to a target Telegram chat or group.",
      parameters: {
        chat_id: "required: The unique chat, user, or group ID.",
      },
    },
    webhook: {
      description: "Submits high-fidelity JSON payloads via HTTP POST.",
      parameters: {
        url: "required: Destination HTTP/HTTPS endpoint.",
        headers: "optional: Custom HTTP headers dictionary.",
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
