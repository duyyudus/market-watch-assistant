import { AlertTriangle } from "lucide-react";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  confirmTone = "btn-error",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  confirmTone?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="modal modal-open" role="dialog" aria-label={title}>
      <div className="modal-box border border-zinc-700 bg-zinc-900">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
          <div>
            <h3 className="text-base font-bold text-zinc-100">{title}</h3>
            <p className="mt-1 text-sm text-zinc-400">{description}</p>
          </div>
        </div>
        <div className="modal-action">
          <button className="btn btn-sm btn-ghost" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className={`btn btn-sm ${confirmTone}`} onClick={onConfirm} type="button">
            {confirmLabel}
          </button>
        </div>
      </div>
      <div className="modal-backdrop" onClick={onCancel} />
    </div>
  );
}
