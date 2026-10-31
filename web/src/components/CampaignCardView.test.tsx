import { cleanup, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CampaignCard } from "../lib/types";
import CampaignCardView from "./CampaignCardView";

const card: CampaignCard = {
  id: "c1",
  name: "Стол",
  world: "Остров",
  status: "active",
  session_live: false,
  waiting_players: 0,
  my_role: "player",
  is_owner: false,
  hero: null,
  party: [],
  recap: null,
  last_session_at: null,
  created_at: "2026-10-20T12:00:00Z",
  cover_url: "/api/campaigns/c1/cover/aw1",
  cover_thumbnail_url: "/api/campaigns/c1/cover/aw1/thumbnail",
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async () => ({ ok: true, blob: async () => new Blob(["x"]) }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:cover");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const show = (featured: boolean, c = card) => render(<MemoryRouter><CampaignCardView c={c} featured={featured} /></MemoryRouter>);

it("главная карточка берёт большую обложку и показывает её", async () => {
  const { findByAltText } = show(true);
  expect(await findByAltText("Обложка мира «Стол»")).toBeTruthy();
  expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([card.cover_url]);
});

it("остальные карточки берут уменьшенную копию", async () => {
  show(false);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([card.cover_thumbnail_url]);
});

it("без обложки карточка не просит картинок", () => {
  show(false, { ...card, cover_url: null, cover_thumbnail_url: null });
  expect(fetchMock).not.toHaveBeenCalled();
});
