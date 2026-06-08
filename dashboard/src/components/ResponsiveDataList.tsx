import type { ReactNode } from "react";

export function ResponsiveDataList({
  cards,
  table,
}: {
  cards: ReactNode;
  table: ReactNode;
}) {
  return (
    <>
      <div className="grid gap-3 lg:hidden">{cards}</div>
      <div className="hidden overflow-x-auto lg:block">{table}</div>
    </>
  );
}
