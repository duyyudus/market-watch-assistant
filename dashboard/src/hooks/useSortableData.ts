import { useMemo, useState } from "react";

import { compareValues } from "../lib/sort";

export function useSortableData<T>(
  items: T[],
  config: { key: string; direction: "asc" | "desc" },
) {
  const [sortConfig, setSortConfig] = useState(config);

  const sortedItems = useMemo(() => {
    const sortableItems = [...items];
    if (sortConfig.key) {
      sortableItems.sort((a, b) => {
        const left = a as Record<string, unknown>;
        const right = b as Record<string, unknown>;
        let aValue: unknown;
        let bValue: unknown;

        if (sortConfig.key === "time") {
          aValue = left.published_at ?? left.fetched_at;
          bValue = right.published_at ?? right.fetched_at;
        } else if (sortConfig.key === "sent") {
          aValue = left.sent_at ?? left.created_at;
          bValue = right.sent_at ?? right.created_at;
        } else if (sortConfig.key === "event_report_range") {
          aValue = (left.event as { report_end_at?: string | null } | undefined)?.report_end_at;
          bValue = (right.event as { report_end_at?: string | null } | undefined)?.report_end_at;
        } else if (sortConfig.key === "event_headline") {
          aValue = (left.event as { headline?: string } | undefined)?.headline ?? left.reason;
          bValue = (right.event as { headline?: string } | undefined)?.headline ?? right.reason;
        } else {
          aValue = left[sortConfig.key];
          bValue = right[sortConfig.key];
        }

        const comp = compareValues(aValue, bValue);
        return sortConfig.direction === "asc" ? comp : -comp;
      });
    }
    return sortableItems;
  }, [items, sortConfig]);

  const requestSort = (key: string) => {
    let direction: "asc" | "desc" = defaultDirectionForKey(key);
    if (sortConfig.key === key && sortConfig.direction === "asc") {
      direction = "desc";
    } else if (sortConfig.key === key && sortConfig.direction === "desc") {
      direction = "asc";
    }
    setSortConfig({ key, direction });
  };

  return { items: sortedItems, requestSort, sortConfig };
}

function defaultDirectionForKey(key: string): "asc" | "desc" {
  if (
    key === "time" ||
    key === "sent" ||
    key === "event_report_range" ||
    key.endsWith("_at")
  ) {
    return "desc";
  }
  return "asc";
}
