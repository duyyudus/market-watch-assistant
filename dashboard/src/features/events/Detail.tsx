import type { ReactNode } from "react";

export function Detail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-base-200 py-1">
      <span className="text-base-content/60">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

