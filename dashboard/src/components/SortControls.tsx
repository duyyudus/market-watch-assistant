import { classNames } from "../lib/classNames";

export type SortControlOption<Key extends string> = {
  key: Key;
  label: string;
};

export function SortControls<Key extends string>({
  label = "Sort by:",
  options,
  currentSortKey,
  direction,
  onSort,
}: {
  label?: string;
  options: SortControlOption<Key>[];
  currentSortKey: Key;
  direction: "asc" | "desc";
  onSort: (key: Key) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11px] text-zinc-500">{label}</span>
      {options.map((option) => {
        const active = currentSortKey === option.key;
        return (
          <button
            className={classNames(
              "flex items-center gap-0.5 transition-colors hover:text-primary",
              active && "font-semibold text-primary",
            )}
            key={option.key}
            onClick={() => onSort(option.key)}
            type="button"
          >
            {option.label}
            {active ? (direction === "asc" ? " ▲" : " ▼") : ""}
          </button>
        );
      })}
    </div>
  );
}
