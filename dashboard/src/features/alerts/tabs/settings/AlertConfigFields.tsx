export type AlertPresetDocItem = {
  description: string;
  parameters: Record<string, string>;
};

export function AlertPresetDoc({
  type,
  presetItem,
}: {
  type: string;
  presetItem?: AlertPresetDocItem;
}) {
  if (!presetItem) return null;

  const hasParams = Object.keys(presetItem.parameters).length > 0;

  return (
    <div className="mt-1 space-y-1 rounded border border-zinc-800/80 bg-zinc-900/50 p-2.5 text-[11px] text-zinc-400">
      <div>
        <span className="font-semibold capitalize text-zinc-300">{type}: </span>
        {presetItem.description}
      </div>
      {hasParams ? (
        <div className="space-y-0.5 border-t border-zinc-800/20 pt-1">
          {Object.entries(presetItem.parameters).map(([key, desc]) => (
            <div key={key}>
              <code className="rounded bg-zinc-900 px-1 py-0.5 font-mono text-[10px] text-teal-400">
                {key}
              </code>
              : {desc}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function JsonConfigField({
  label,
  value,
  valid,
  onChange,
}: {
  label: string;
  value: string;
  valid: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative">
      <textarea
        aria-label={label}
        className={`textarea textarea-bordered min-h-28 w-full p-3 font-mono text-xs ${
          !valid ? "textarea-error border-red-500 focus:border-red-500" : ""
        }`}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
      {!valid ? (
        <span className="absolute bottom-3 right-3 rounded border border-red-500/30 bg-black/80 px-1.5 py-0.5 text-[10px] font-semibold text-red-500">
          Invalid JSON
        </span>
      ) : null}
    </div>
  );
}
