import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NewsTable } from "./NewsTable";

const rows = [
  {
    id: "news_1",
    title: "Fed signals a slower rate path",
    source_name: "Federal Reserve",
    source_type: "official",
    source_score: 100,
    region: "us",
    asset_classes: ["global_macro"],
    processing_status: "clustered",
    published_at: "2026-05-29T13:00:00Z",
    fetched_at: "2026-05-29T13:01:00Z",
  },
];

describe("NewsTable", () => {
  it("renders both responsive cards and the desktop table", () => {
    render(<NewsTable rows={rows} retry={vi.fn()} />);

    expect(screen.getByTestId("news-card-news_1")).toHaveTextContent("Fed signals a slower rate path");
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
