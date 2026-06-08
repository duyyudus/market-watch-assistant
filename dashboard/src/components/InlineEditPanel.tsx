import { X } from "lucide-react";
import type { ReactNode, Ref } from "react";

export function InlineEditPanel({
  title,
  error,
  children,
  panelRef,
  className = "",
  onCancel,
}: {
  title: string;
  error?: string | null;
  children: ReactNode;
  panelRef?: Ref<HTMLDivElement>;
  className?: string;
  onCancel: () => void;
}) {
  return (
    <div
      ref={panelRef}
      className={`mb-5 rounded-md border border-zinc-800 bg-zinc-950/40 p-4 ${className}`}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-zinc-200">{title}</div>
        <button className="btn btn-xs btn-ghost" onClick={onCancel} type="button">
          <X className="h-4 w-4" />
          Cancel
        </button>
      </div>
      {error ? <div className="alert alert-error mb-3 text-sm">{error}</div> : null}
      {children}
    </div>
  );
}
