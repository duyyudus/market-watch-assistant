import { RefreshCcw } from "lucide-react";

export function SectionError({
  title,
  message,
  retry,
}: {
  title: string;
  message: string;
  retry: () => Promise<void>;
}) {
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm">
      <div className="font-bold text-warning">{title}</div>
      <div className="mt-1 break-words text-base-content/70">{message}</div>
      <button className="btn btn-warning btn-xs mt-3" onClick={() => void retry()} type="button">
        <RefreshCcw className="h-3.5 w-3.5" />
        Retry
      </button>
    </div>
  );
}

