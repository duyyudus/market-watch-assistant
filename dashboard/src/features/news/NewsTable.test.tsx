import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NewsTable } from "./NewsTable";

const rows = [
  {
    id: "news_1",
    source_id: "src_1",
    title: "Fed signals a slower rate path",
    source_name: "Federal Reserve",
    source_type: "official",
    source_score: 100,
    url: "https://www.example.com/news",
    canonical_url: "https://example.com/news",
    region: "us",
    asset_classes: ["global_macro"],
    processing_status: "clustered",
    published_at: "2026-05-29T13:00:00Z",
    fetched_at: "2026-05-29T13:01:00Z",
  },
];

describe("NewsTable", () => {
  it("renders both responsive cards and the desktop table", () => {
    render(
      <NewsTable
        rows={rows}
        retry={vi.fn()}
        selectedNewsId={null}
        selectedNewsDetail={null}
        selectNews={vi.fn()}
        limit={100}
        setLimit={vi.fn()}
        offset={0}
        total={rows.length}
        setOffset={vi.fn()}
        domain=""
        setDomain={vi.fn()}
        domainOptions={["example.com"]}
        sourceId=""
        setSourceId={vi.fn()}
        sourceOptions={[{ id: "src_1", name: "Federal Reserve", source_type: "official" }]}
        status=""
        setStatus={vi.fn()}
        statusOptions={["clustered"]}
        region=""
        setRegion={vi.fn()}
        regionOptions={["us"]}
      />,
    );

    expect(screen.getByTestId("news-card-news_1")).toHaveTextContent("Fed signals a slower rate path");
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("exposes article-domain source status region and page-size controls", () => {
    const setDomain = vi.fn();
    const setLimit = vi.fn();
    const setSourceId = vi.fn();
    const setStatus = vi.fn();
    const setRegion = vi.fn();

    render(
      <NewsTable
        rows={rows}
        retry={vi.fn()}
        selectedNewsId={null}
        selectedNewsDetail={null}
        selectNews={vi.fn()}
        limit={100}
        setLimit={setLimit}
        offset={0}
        total={250}
        setOffset={vi.fn()}
        domain=""
        setDomain={setDomain}
        domainOptions={["example.com", "oil.example.org"]}
        sourceId=""
        setSourceId={setSourceId}
        sourceOptions={[
          { id: "src_1", name: "Federal Reserve", source_type: "official" },
          { id: "src_2", name: "Oil Wire", source_type: "rss" },
        ]}
        status=""
        setStatus={setStatus}
        statusOptions={["clustered", "new"]}
        region=""
        setRegion={setRegion}
        regionOptions={["global", "us"]}
      />,
    );

    expect(screen.getByRole("option", { name: "oil.example.org" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Oil Wire · rss" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "clustered" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "global" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Source domain"), {
      target: { value: "oil.example.org" },
    });
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "src_2" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "new" } });
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "global" } });
    fireEvent.change(screen.getByLabelText("Items per page"), { target: { value: "200" } });

    expect(setDomain).toHaveBeenCalledWith("oil.example.org");
    expect(setSourceId).toHaveBeenCalledWith("src_2");
    expect(setStatus).toHaveBeenCalledWith("new");
    expect(setRegion).toHaveBeenCalledWith("global");
    expect(setLimit).toHaveBeenCalledWith(200);
  });

  it("uses fetch limit as page size and exposes paging controls", () => {
    const setOffset = vi.fn();

    render(
      <NewsTable
        rows={rows}
        retry={vi.fn()}
        selectedNewsId={null}
        selectedNewsDetail={null}
        selectNews={vi.fn()}
        limit={100}
        setLimit={vi.fn()}
        offset={100}
        total={250}
        setOffset={setOffset}
        domain=""
        setDomain={vi.fn()}
        domainOptions={["example.com"]}
        sourceId=""
        setSourceId={vi.fn()}
        sourceOptions={[{ id: "src_1", name: "Federal Reserve", source_type: "official" }]}
        status=""
        setStatus={vi.fn()}
        statusOptions={["clustered"]}
        region=""
        setRegion={vi.fn()}
        regionOptions={["us"]}
      />,
    );

    expect(screen.getByText("101-200 of 250")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(setOffset).toHaveBeenNthCalledWith(1, 0);
    expect(setOffset).toHaveBeenNthCalledWith(2, 200);
  });

  it("selects a news item and renders the detail panel", () => {
    const selectNews = vi.fn();

    render(
      <NewsTable
        rows={rows}
        retry={vi.fn()}
        selectedNewsId="news_1"
        selectedNewsDetail={{
          ...rows[0],
          source_id: "src_1",
          snippet: "Policy makers leaned less hawkish.",
          raw_content: "Full normalized article text.",
          language: "en",
          is_paywalled: false,
          full_text_available: true,
          full_text_extraction_status: "success",
          full_text_attempt_count: 1,
          full_text_last_attempted_at: "2026-05-29T13:02:00Z",
          full_text_last_http_status: 200,
          full_text_last_error: null,
          full_text_next_retry_at: null,
          entities: [
            {
              id: "ent_1",
              entity_type: "organization",
              raw_text: "Federal Reserve",
              normalized_name: "Japan (Nikkei 225; government growth revision)",
              ticker: null,
              exchange: null,
              country: "US",
              confidence: 96,
            },
          ],
          clusters: [
            {
              event_cluster_id: "evt_1",
              relation_type: "seed",
              similarity_score: 91,
              decision_metadata: null,
              added_at: "2026-05-29T13:03:00Z",
            },
          ],
        }}
        selectNews={selectNews}
        limit={100}
        setLimit={vi.fn()}
        offset={0}
        total={rows.length}
        setOffset={vi.fn()}
        domain=""
        setDomain={vi.fn()}
        domainOptions={["example.com"]}
        sourceId=""
        setSourceId={vi.fn()}
        sourceOptions={[{ id: "src_1", name: "Federal Reserve", source_type: "official" }]}
        status=""
        setStatus={vi.fn()}
        statusOptions={["clustered"]}
        region=""
        setRegion={vi.fn()}
        regionOptions={["us"]}
      />,
    );

    fireEvent.click(screen.getByTestId("news-row-news_1"));

    expect(selectNews).toHaveBeenCalledWith("news_1");
    expect(screen.getByText("Article detail")).toBeInTheDocument();
    const metadataButton = screen.getByRole("button", { name: "Metadata" });
    expect(metadataButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("news_1")).not.toBeInTheDocument();
    fireEvent.click(metadataButton);
    expect(metadataButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("news_1")).toBeInTheDocument();
    expect(screen.getByText("Policy makers leaned less hawkish.")).toBeInTheDocument();
    expect(screen.getByText("Full normalized article text.")).toBeInTheDocument();
    const entityChip = screen.getByTestId("news-entity-ent_1");
    expect(entityChip).toHaveTextContent("Japan (Nikkei 225; government growth revision)");
    expect(screen.getByText("Japan (Nikkei 225; government growth revision)")).toHaveClass(
      "whitespace-normal",
    );
    expect(screen.getByText("evt_1")).toBeInTheDocument();
  });
});
