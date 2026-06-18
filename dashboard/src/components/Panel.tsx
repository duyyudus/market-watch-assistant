import type { ReactNode } from "react";

import { classNames } from "../lib/classNames";

export function Panel({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={title}
      className={classNames(
        "overflow-hidden rounded-xl border border-zinc-800/80 bg-zinc-900/60 shadow-lg shadow-black/10 backdrop-blur-md",
        className,
      )}
    >
      <div className="border-b border-zinc-800/60 bg-zinc-900/40 px-5 py-4">
        <h3 className="text-sm font-bold text-zinc-200 tracking-widest uppercase">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}
