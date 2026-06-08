import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DashboardErrorBoundary } from "./ErrorBoundary";

function BrokenPanel() {
  throw new Error("render failed");
  return null;
}

describe("DashboardErrorBoundary", () => {
  it("renders a dashboard fallback when a child throws", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <DashboardErrorBoundary>
        <BrokenPanel />
      </DashboardErrorBoundary>,
    );

    expect(screen.getByText("Dashboard section failed")).toBeInTheDocument();
    expect(screen.getByText(/render failed/i)).toBeInTheDocument();

    consoleError.mockRestore();
  });
});
