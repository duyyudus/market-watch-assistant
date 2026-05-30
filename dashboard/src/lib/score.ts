export function scoreTone(score: number) {
  if (score >= 80) return "error";
  if (score >= 55) return "warning";
  if (score >= 30) return "info";
  return "neutral";
}

