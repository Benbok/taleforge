import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import WorldDetailPage from "./WorldDetailPage";
import type { WorldDetail } from "../lib/worlds";

const mockWorld: WorldDetail = {
  id: "echo-leviathans",
  name: "Эхо Левиафанов",
  version: "0.2.6",
  category: "ОСНОВНОЙ СЕТТИНГ · БИОПАНК / ДИЗЕЛЬПАНК",
  summary: "Мир титанов, павших сорок лет назад.",
  description: "Сорок лет назад титаны пали с небес. На их гигантских телах человечество построило цивилизацию.",
  ruleset: "dnd5e",
  ruleset_base: "srd-5.1",
  level_cap: 15,
  badges: ["Шкалы: Скверна и Перемена", "Уровни: 1–15"],
  status_badge: "АКТИВЕН В СИСТЕМЕ",
  is_base: false,
  counts: { faction: 1, location_template: 1, origin: 1, class: 1, creature_template: 1 },
  lore_topics: [
    {
      topic: "cosmology",
      title: "Космология и основы мира",
      facts: [
        {
          id: "lore.three_forces",
          name: "Три силы",
          text: "Мир стоит на треугольнике: экипажи Левиафанов, Резонанс и люди.",
          tags: ["cosmology"],
        },
      ],
    },
  ],
  factions: [
    {
      id: "faction.syndicates",
      name: "Синдикаты Крови",
      description: "Совет трёх Домов, делящих Средний пояс.",
      goal: "Сохранить власть и добычу субстанций.",
      resources: ["Железные дороги", "Шахты"],
      relations: [],
    },
  ],
  locations: [
    {
      id: "location.city_gornilo",
      name: "Горнило",
      description: "Город печей Кострищевых на великой туше.",
      location_type: "hulk",
      population: 180000,
      ruler: "Лука Кострищев",
      districts: [{ name: "Печной канал", text: "Мозговые печи" }],
      tags: ["hulk", "city"],
    },
  ],
  origins: [
    {
      id: "origin.tushevik",
      name: "Тушевик",
      epithet: "Рождённый на туше",
      badge: "Люди · Туша",
      summary: "Крепкий житель туши.",
      description: "Привык к трупному газу и теплу.",
      ability_bonuses: [{ ability: "con", value: 2 }],
      formatted_bonuses: "+2 к Телосложению, +1 к любой другой на выбор",
      speed: 30,
      speed_display: "30 футов (9 м)",
      size: "medium",
      size_display: "Средний",
      highlights: ["Привычка к газу", "Чувство туши"],
      features: [{ name: "Привычка к газу", description: "Преимущество против яда" }],
    },
  ],
  classes: [
    {
      id: "class.diagnost",
      name: "Диагност",
      epithet: "Врач и химик Гильдии",
      badge: "Гильдия · Ликвор",
      summary: "Полевой врач и алхимик.",
      description: "Учёный Гильдии, лечит и слушает туши.",
      hit_die: "d8",
      highlights: ["Диагностика", "Полевые препараты"],
      subclasses: [{ id: "subclass.medic", name: "Полевой медик" }],
    },
  ],
  scales: [
    {
      id: "stat.corruption",
      name: "Скверна",
      description: "Шкала 0–6 поражения Резонансом.",
      widget_type: "track",
      min: 0,
      max: 6,
      tags: ["corruption"],
    },
  ],
  clocks: [
    {
      id: "clock.resonance_power",
      name: "Сила Резонанса",
      description: "Глобальные часы кампании.",
      scope: "campaign",
      min: 0,
      max: 10,
      moves_up: ["новые Глубинные"],
      moves_down: ["освобождённые дети"],
      thresholds: [],
    },
  ],
  bestiary: [
    {
      id: "creature.brood",
      name: "Выводок Резонанса",
      description: "Чудовище черты.",
      cr: "2",
      kind: "brood",
      tags: ["brood"],
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("renders world detail with tabs, factions, locations and classes", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/worlds/echo-leviathans")) {
      return new Response(JSON.stringify(mockWorld), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({}), { status: 404 });
  });
  vi.stubGlobal("fetch", fetcher);

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/worlds/echo-leviathans"]}>
        <Routes>
          <Route path="/worlds/:worldId" element={<WorldDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );

  // Checks header and name
  expect(await screen.findByText("Эхо Левиафанов")).toBeTruthy();
  expect(screen.getByText("ОСНОВНОЙ СЕТТИНГ · БИОПАНК / ДИЗЕЛЬПАНК")).toBeTruthy();
  expect(screen.getByText("Шкалы: Скверна и Перемена")).toBeTruthy();

  // Overview tab shows lore fact
  expect(await screen.findByText("Три силы")).toBeTruthy();
  expect(screen.getByText("Мир стоит на треугольнике: экипажи Левиафанов, Резонанс и люди.")).toBeTruthy();

  // Switch to Factions tab
  fireEvent.click(screen.getByRole("button", { name: /Фракции/ }));
  expect(await screen.findByText("Синдикаты Крови")).toBeTruthy();
  expect(screen.getByText("Совет трёх Домов, делящих Средний пояс.")).toBeTruthy();

  // Switch to Locations tab
  fireEvent.click(screen.getByRole("button", { name: /Атлас и Локации/ }));
  expect(await screen.findByText("Горнило")).toBeTruthy();
  expect(screen.getByText("Печной канал")).toBeTruthy();

  // Switch to Characters tab
  fireEvent.click(screen.getByRole("button", { name: /Народы и Классы/ }));
  expect(await screen.findByText("Тушевик")).toBeTruthy();
  expect(screen.getByText("+2 к Телосложению, +1 к любой другой на выбор")).toBeTruthy();
  expect(screen.getByText("Скорость 30 футов (9 м)")).toBeTruthy();
  expect(screen.getByText("Средний")).toBeTruthy();
  expect(screen.getByText("Диагност")).toBeTruthy();
  expect(screen.getByText("Полевой медик")).toBeTruthy();

  // Switch to Mechanics tab
  fireEvent.click(screen.getByRole("button", { name: /Шкалы и Механики/ }));
  expect(await screen.findByText("Сила Резонанса")).toBeTruthy();
  expect(screen.getByText("Скверна")).toBeTruthy();

  // Switch to Bestiary tab
  fireEvent.click(screen.getByRole("button", { name: /Бестиарий/ }));
  expect(await screen.findByText("Выводок Резонанса")).toBeTruthy();
});
