import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { WatchedTopicsModal } from "./WatchedTopicsModal";

vi.mock("../../api", () => ({ api: { watchedTopics: vi.fn(), updateWatchedTopics: vi.fn() } }));

beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  vi.mocked(api.watchedTopics).mockResolvedValue({ topics: ["Luật bất động sản"] });
  vi.mocked(api.updateWatchedTopics).mockResolvedValue({ topics: [] });
});
afterEach(cleanup);

describe("Watched Topics editor", () => {
  it("loads, edits, adds, removes and saves phrases", async () => {
    const close = vi.fn();
    render(<WatchedTopicsModal onClose={close} />);
    const first = await screen.findByLabelText("Topic 1");
    fireEvent.change(first, { target: { value: " Chính sách thuế tài sản số " } });
    fireEvent.click(screen.getByText("Add topic"));
    fireEvent.change(screen.getByLabelText("Topic 2"), { target: { value: "FOMC" } });
    fireEvent.click(screen.getByLabelText("Remove topic 2"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(api.updateWatchedTopics).toHaveBeenCalledWith({ topics: ["Chính sách thuế tài sản số"] });
  });

  it("discards edits on Cancel and Escape", async () => {
    const close = vi.fn();
    render(<WatchedTopicsModal onClose={close} />);
    await screen.findByLabelText("Topic 1");
    fireEvent.click(screen.getByLabelText("Remove topic 1"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(close).toHaveBeenCalledOnce();
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true, cancelable: true }));
    expect(close).toHaveBeenCalledTimes(2);
    expect(api.updateWatchedTopics).not.toHaveBeenCalled();
  });

  it("keeps edits on failed save and permits retry", async () => {
    vi.mocked(api.updateWatchedTopics).mockRejectedValueOnce(new Error("Unauthorized"));
    render(<WatchedTopicsModal onClose={vi.fn()} />);
    await screen.findByLabelText("Topic 1");
    fireEvent.click(screen.getByText("Save"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unauthorized");
    expect(screen.getByLabelText("Topic 1")).toHaveValue("Luật bất động sản");
    expect(screen.getByText("Save")).toBeEnabled();
  });

  it("prevents saving while loading or after a load error", async () => {
    vi.mocked(api.watchedTopics).mockRejectedValueOnce(new Error("Offline"));
    render(<WatchedTopicsModal onClose={vi.fn()} />);
    expect(screen.getByText("Save")).toBeDisabled();
    expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
    expect(screen.getByText("Save")).toBeDisabled();
  });

  it("validates blank and duplicate phrases, and supports clearing the list", async () => {
    render(<WatchedTopicsModal onClose={vi.fn()} />);
    await screen.findByLabelText("Topic 1");
    fireEvent.click(screen.getByText("Add topic"));
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByRole("alert")).toHaveTextContent("1–300");
    fireEvent.change(screen.getByLabelText("Topic 2"), { target: { value: "Luật bất động sản" } });
    fireEvent.click(screen.getByText("Save"));
    expect(screen.getByRole("alert")).toHaveTextContent("unique");
    fireEvent.click(screen.getByLabelText("Remove topic 2"));
    fireEvent.click(screen.getByLabelText("Remove topic 1"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(api.updateWatchedTopics).toHaveBeenCalledWith({ topics: [] }));
  });
});
