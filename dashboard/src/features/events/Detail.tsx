import type { ReactNode } from "react";

import { MetadataRow } from "../../components/MetadataRow";

export function Detail({ label, value }: { label: string; value: ReactNode }) {
  return <MetadataRow label={label} value={value} />;
}
