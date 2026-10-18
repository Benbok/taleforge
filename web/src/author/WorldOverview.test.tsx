import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { WorldOverview as Overview } from "../lib/api.gen";
import WorldOverview from "./WorldOverview";

afterEach(cleanup);

const overview: Overview = {
  regions: { reg_deep: "Глубины" },
  locations: [
    {
      ref: "loc_cave",
      name: "Пещера",
      region: "reg_deep",
      areas: [
        { area_ref: "main", name: "Вход", entry: true, secret: false, npcs: [], items: [] },
        { area_ref: "crawl", name: "Узкий лаз", entry: false, secret: true, npcs: ["Лис"], items: ["Ключ"] },
      ],
      passages: [{ from_area: "main", to_area: "crawl", name: "Щель", kind: "gap", hidden: true }],
    },
    { ref: "loc_hall", name: "Зал", areas: [{ area_ref: "main", name: "Зал Ничто", entry: true, secret: false, npcs: [], items: [] }], passages: [] },
  ],
  routes: [{ ref: "r1", from_ref: "loc_cave", from_area: "crawl", to_ref: "loc_hall", to_area: "main", bidirectional: false, hidden: false }],
};

it("рисует места, участки, проходы и маршруты и рассказывает, кто где", () => {
  const { container } = render(<WorldOverview overview={overview} />);
  expect(container.querySelectorAll("[data-location]").length).toBe(2);
  expect(screen.getByText("Глубины")).toBeTruthy();
  expect(container.querySelector('path[marker-end="url(#ov-arrow)"]')).not.toBeNull(); // односторонний маршрут
  expect(container.querySelector('path[stroke-dasharray="4 4"]')).not.toBeNull(); // тайный проход внутри места
  fireEvent.click(screen.getByRole("button", { name: "Пещера: Узкий лаз" }));
  const details = screen.getByRole("region", { name: "Подробности" });
  expect(within(details).getByText(/Лис/)).toBeTruthy();
  expect(within(details).getByText(/Ключ/)).toBeTruthy();
  expect(details.textContent).toContain("→ Зал · Зал Ничто");
  expect(details.textContent).toContain("Щель → Вход");
});

it("без мест объясняет, когда появится схема", () => {
  render(<WorldOverview overview={{ locations: [], routes: [], regions: {} }} />);
  expect(screen.getByText(/схема появится после шага/)).toBeTruthy();
});
