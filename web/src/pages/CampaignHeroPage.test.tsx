import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { Waiting } from "./CampaignHeroPage";
import { api } from "../lib/api";
import type { CampaignHero } from "../lib/builder";

vi.mock("../lib/api", () => ({ api: vi.fn() }));
afterEach(cleanup);

test("retry hides previous failure immediately and displays the next final result", async () => {
  let release!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  const old = { id: "hero", name: "Бран", status: "submitted", reviewer: "ai",
    review_status: "failed", review_error: "Previous failure" } as CampaignHero;
  const onRetry = vi.fn(async () => undefined);
  const ui = (hero: CampaignHero) => <MemoryRouter><Waiting id="c" hero={hero} onRetry={onRetry} /></MemoryRouter>;
  const view = render(ui(old));
  expect(screen.queryByText("Previous failure")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "ПОВТОРИТЬ ПРОВЕРКУ ИИ" }));
  await waitFor(() => expect(screen.queryByText("Previous failure")).toBeNull());
  expect(screen.queryByText(/Проверка выполняется/)).not.toBeNull();
  release({ attempt_id: "new", review_status: "running" });
  await waitFor(() => expect(onRetry).toHaveBeenCalledOnce());
  view.rerender(ui({ ...old, review_status: "running", review_error: null }));
  expect(screen.queryByText("Previous failure")).toBeNull();
  view.rerender(ui({ ...old, review_error: "New failure", review_status: "failed" }));
  expect(screen.queryByText("New failure")).not.toBeNull();
  view.unmount();
  render(ui({ ...old, review_error: "New failure", review_status: "failed" }));
  expect(screen.queryByText("New failure")).not.toBeNull();
});
