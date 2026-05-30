import type { ReactNode } from "react";

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/60 shadow-lg shadow-black/10 backdrop-blur-md overflow-hidden">
      <div className="border-b border-zinc-800/60 bg-zinc-900/40 px-5 py-4">
        <h3 className="text-sm font-bold text-zinc-200 tracking-widest uppercase">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

