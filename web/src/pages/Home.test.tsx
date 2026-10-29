import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mockApi, renderWithClient } from "../author/testkit";
import type { CampaignCard } from "../lib/types";
import { useSession } from "../stores/session";
import Home from "./Home";

vi.mock("../components/Header", () => ({
  default: ({ onTabChange }: { onTabChange: (tab: string) => void }) => (
    <nav>
      <button onClick={() => onTabChange("worlds")}>Миры</button>
    </nav>
  ),
}));

const card = (id: string, patch: Partial<CampaignCard> = {}): CampaignCard => ({
  id,
  name: `Стол ${id}`,
  world: "Туманный остров",
  status: "active",
  session_live: false,
  waiting_players: 0,
  my_role: "player",
  is_owner: false,
  hero: { id: "hero", name: "Лира", status: "approved", level: 2 },
  party: [],
  recap: "Следы ведут к старому маяку.",
  last_session_at: "2026-10-25T12:00:00Z",
  created_at: "2026-10-20T12:00:00Z",
  ...patch,
});

function mount(cards: CampaignCard[], worldsError = false, route = "/") {
  mockApi(({ url }) => {
    if (url === "/api/me/campaigns") return { body: cards };
    if (url === "/api/me/characters") return { body: [] };
    if (url === "/api/adventures/catalog")
      return {
        status: worldsError ? 500 : 200,
        body: worldsError ? { detail: "Ошибка каталога" } : [],
      };
    return undefined;
  });
  return renderWithClient(<Home />, undefined, route);
}

beforeEach(() => {
  useSession.setState({
    user: {
      id: "u1",
      name: "Арти",
      platform_role: "admin",
      menu_music: { enabled: false, volume: 0.5 },
    },
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("выделяет живую сессию один раз и показывает закреплённую версию", async () => {
  mount([
    card("old"),
    card("live", { session_live: true, world_version: "3" }),
  ]);
  const title = await screen.findByRole("heading", {
    level: 2,
    name: "Стол live",
  });
  const featured = title.closest("article")!;
  expect(within(featured).getByText(/версия 3/i)).toBeTruthy();
  expect(
    within(featured)
      .getByRole("link", { name: /Продолжить/ })
      .getAttribute("href"),
  ).toBe("/c/live");
  expect(screen.getAllByText("Стол live")).toHaveLength(1);
  expect(screen.queryByText(/5e|SRD|СВОДКА ПЕПЕЛЬНОЙ/)).toBeNull();
});

it("выбирает недавнее незавершённое приключение и применяет ролевые фильтры", async () => {
  mount([
    card("ended", { status: "ended", session_live: true }),
    card("older"),
    card("recent", {
      my_role: "master",
      last_session_at: "2026-10-28T12:00:00Z",
    }),
  ]);
  await screen.findByRole("heading", { level: 2, name: "Стол recent" });
  fireEvent.click(screen.getByRole("button", { name: /Я игрок/ }));
  expect(screen.queryByRole("heading", { name: "Стол recent" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Стол older" })).toBeTruthy();
});

it("не выдумывает мир и версию для старого стола", async () => {
  mount([card("legacy", { world: null, status: "lobby", hero: null })]);
  await screen.findByRole("heading", { name: "Стол legacy" });
  expect(screen.getByText("Авторский мир")).toBeTruthy();
  expect(screen.queryByText(/версия/i)).toBeNull();
  expect(
    screen.getByRole("link", { name: "Собрать героя" }).getAttribute("href"),
  ).toBe("/c/legacy/hero");
});

it("показывает ошибку каталога вместо резервных миров 5e", async () => {
  mount([], true);
  fireEvent.click(screen.getAllByRole("button", { name: "Миры" })[0]);
  expect(await screen.findByText(/Не удалось загрузить миры/)).toBeTruthy();
  expect(screen.queryByText(/D&D|SRD|Эхо Левиафанов/)).toBeNull();
});

it("открывает каталог опубликованных миров по ссылке нового приключения", async () => {
  mount([], false, "/?tab=worlds");
  expect(await screen.findByText(/Пока нет опубликованных миров/)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Ваши приключения" })).toBeNull();
});
