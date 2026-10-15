import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ReviewCard } from "./PlayersTab";
import { api } from "../lib/api";
import type { CampaignHero } from "../lib/builder";

vi.mock("../lib/api", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("retry refreshes the cached failure before ending the running state", async () => {
  const hero = { id: "hero", name: "Bran", status: "submitted", reviewer: "ai",
    review_status: "failed", review_error: "Previous failure" } as CampaignHero;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["character", "campaign", hero.id], hero);
  let finishPost!: (value: unknown) => void;
  let finishRefresh!: (value: unknown) => void;
  vi.mocked(api)
    .mockImplementationOnce(() => new Promise((resolve) => { finishPost = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
  const onDone = vi.fn(async () => undefined);
  render(<QueryClientProvider client={client}>
    <ReviewCard campaignId="campaign" hero={hero} onDone={onDone} />
  </QueryClientProvider>);
  expect(screen.queryByText(/Previous failure/)).not.toBeNull();
  const retry = screen.getByRole("button", { name: /Повторить проверку ИИ/ });
  fireEvent.click(retry);
  expect(screen.queryByText(/Previous failure/)).toBeNull();
  await act(async () => { finishPost({ review_status: "running", attempt_id: "new" }); });
  // No polling timer has elapsed: retry must explicitly refresh the detail query.
  expect(api).toHaveBeenCalledTimes(2);
  expect(screen.queryByText(/Previous failure/)).toBeNull();
  expect((retry as HTMLButtonElement).disabled).toBe(true);
  await act(async () => { finishRefresh({ ...hero, review_status: "running", review_error: null }); });
  await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
  await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("false"));
  expect(screen.queryByText(/Previous failure/)).toBeNull();
  expect(screen.queryByRole("status")).not.toBeNull();
  expect((retry as HTMLButtonElement).disabled).toBe(true);
  client.clear();
});
