import type { ReactNode } from "react";

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-5 shadow-lg shadow-black/10 backdrop-blur-md">
      <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="mt-2 text-4xl font-black text-zinc-100 tracking-tight">{value}</div>
    </div>
  );
}

