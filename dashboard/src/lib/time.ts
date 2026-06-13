export function formatTime(value?: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatTimeRange(start?: string | null, end?: string | null) {
  if (!start && !end) return "-";
  if (!start) return formatTime(end);
  if (!end || start === end) return formatTime(start);
  return `${formatTime(start)} - ${formatTime(end)}`;
}
