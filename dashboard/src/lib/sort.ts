export function compareValues(a: unknown, b: unknown) {
  if (a === b) return 0;
  if (a == null) return -1;
  if (b == null) return 1;

  if (typeof a === "string" && typeof b === "string") {
    const aTime = Date.parse(a);
    const bTime = Date.parse(b);
    const isADate = a.includes("-") || a.includes(":");
    const isBDate = b.includes("-") || b.includes(":");
    if (isADate && isBDate && !Number.isNaN(aTime) && !Number.isNaN(bTime)) {
      return aTime - bTime;
    }
    return a.localeCompare(b);
  }

  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }

  if (typeof a === "boolean" && typeof b === "boolean") {
    return a === b ? 0 : a ? 1 : -1;
  }

  return String(a).localeCompare(String(b));
}

