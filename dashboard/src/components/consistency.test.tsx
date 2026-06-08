import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FeatureTabs } from "./FeatureTabs";
import { InlineEditPanel } from "./InlineEditPanel";
import { MetadataRow } from "./MetadataRow";
import { SortControls } from "./SortControls";
import { StatusBadge } from "./StatusBadge";

describe("shared dashboard consistency components", () => {
  it("renders tabs, form shells, metadata, status badges, and sort controls consistently", () => {
    const onTabChange = vi.fn();
    const onSort = vi.fn();

    render(
      <div>
        <FeatureTabs
          activeTab="configured"
          tabs={[
            { id: "configured", label: "Configured" },
            { id: "health", label: "Health" },
          ]}
          onChange={onTabChange}
        />
        <InlineEditPanel title="Edit source" onCancel={() => undefined}>
          <button type="button">Save source</button>
        </InlineEditPanel>
        <MetadataRow label="Event ID" value="evt_1" />
        <StatusBadge tone="success">confirmed</StatusBadge>
        <SortControls
          label="Sort by:"
          currentSortKey="name"
          direction="asc"
          options={[
            { key: "name", label: "Name" },
            { key: "status", label: "Status" },
          ]}
          onSort={onSort}
        />
      </div>,
    );

    expect(screen.getByRole("button", { name: "Configured" })).toHaveClass("tab-active");
    expect(screen.getByText("Edit source")).toBeInTheDocument();
    expect(screen.getByText("Event ID")).toBeInTheDocument();
    expect(screen.getByText("evt_1")).toBeInTheDocument();
    expect(screen.getByText("confirmed")).toHaveClass("badge-success");
    expect(screen.getByRole("button", { name: "Name ▲" })).toBeInTheDocument();
  });
});
