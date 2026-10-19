import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import CanonJournal from "./CanonJournal";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><CanonJournal campaignId="c1" /></QueryClientProvider>);
}

test("lists what the master added with its kind and reason", async () => {
  vi.mocked(api).mockResolvedValueOnce({
    entries: [{ event_id: "ev1", tool: "keep_found_item", kind: "Находка в инвентаре героя", name: "Бумаги", reason: "тайник под столом" }],
  });
  view();
  expect(await screen.findByText("Бумаги")).not.toBeNull();
  expect(screen.getByText("Находка в инвентаре героя")).not.toBeNull();
  expect(screen.getByText("тайник под столом")).not.toBeNull();
  expect(api).toHaveBeenCalledWith("/api/campaigns/c1/canon-journal");
});

test("says so when the master added nothing", async () => {
  vi.mocked(api).mockResolvedValueOnce({ entries: [] });
  view();
  await waitFor(() => expect(screen.queryByText("Пока мастер ничего не добавлял.")).not.toBeNull());
});
