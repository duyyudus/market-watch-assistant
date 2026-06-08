import type { ReactNode } from "react";

export type StatusBadgeTone = "neutral" | "info" | "success" | "warning" | "error";

export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: StatusBadgeTone;
}) {
  return <span className={`badge badge-sm badge-${tone}`}>{children}</span>;
}
