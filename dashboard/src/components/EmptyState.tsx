import { Activity, Database, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: Icon = Database,
  title,
  body,
  action,
}: {
  icon?: LucideIcon | typeof Activity;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center rounded-lg border border-dashed border-zinc-800 bg-zinc-950/30 px-5 py-8 text-center">
      <Icon className="h-6 w-6 text-zinc-500" />
      <h4 className="mt-3 text-sm font-bold text-zinc-200">{title}</h4>
      <p className="mt-1 max-w-md text-sm text-base-content/60">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

