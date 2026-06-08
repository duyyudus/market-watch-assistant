import type { ReactNode } from "react";

export function MetadataRow({ label, value }: { label: string; value: ReactNode }) {
  const displayValue = value === null || value === undefined || value === "" ? "-" : value;

  return (
    <div className="flex justify-between gap-4 border-b border-zinc-800/60 py-1.5 text-sm">
      <span className="text-base-content/60">{label}</span>
      <span className="text-right font-medium text-zinc-200">{displayValue}</span>
    </div>
  );
}
