import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { classNames } from "../lib/classNames";

export function SortableHeader({
  label,
  sortKey,
  currentSortKey,
  direction,
  onSort,
  className,
}: {
  label: string;
  sortKey: string;
  currentSortKey: string;
  direction: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const isActive = currentSortKey === sortKey;
  return (
    <th
      className={classNames("py-3 px-4 font-semibold text-left cursor-pointer hover:bg-zinc-800/40 select-none transition-colors duration-150 group", className)}
      onClick={() => onSort(sortKey)}
    >
      <div className="flex items-center gap-1.5">
        <span>{label}</span>
        {isActive ? (
          direction === "asc" ? (
            <ArrowUp className="h-3.5 w-3.5 text-primary" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5 text-primary" />
          )
        ) : (
          <ArrowUpDown className="h-3.5 w-3.5 text-zinc-600 opacity-30 group-hover:opacity-100 transition-opacity" />
        )}
      </div>
    </th>
  );
}

