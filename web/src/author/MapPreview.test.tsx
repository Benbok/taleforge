import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AuthorMapOut } from "../lib/api.gen";
import MapPreview from "./MapPreview";

const sketch = { shape: "room", cols: 6, rows: 4, party: [1, 1], walls: [], exits: [], features: [], terrain: [], edges: [] };
const map = {
  location_ref: "loc_cave",
  name: "Пещера",
  areas: [
    { area_ref: "main", name: "Вход", sketch, ports: { r1: { cells: [[1, 1]] } } },
    { area_ref: "crawl", name: "Узкий лаз", sketch, ports: {} },
  ],
} as unknown as AuthorMapOut;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("рисует выбранный участок через LocationMapSvg и сообщает о выборе только через callback", () => {
  const fetchMock = vi.fn();
  const socket = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("WebSocket", socket);
  const onSelect = vi.fn();
  const { container } = render(<MapPreview map={map} onSelect={onSelect} />);
  expect(container.querySelector("[data-location-map]")).not.toBeNull();
  expect(screen.getByLabelText("Порты маршрутов").textContent).toContain("r1");
  fireEvent.click(screen.getByRole("button", { name: "Узкий лаз" }));
  expect(onSelect).toHaveBeenCalledWith("crawl");
  expect(screen.getByRole("button", { name: "Узкий лаз" }).getAttribute("aria-pressed")).toBe("true");
  // просмотр карты не ходит в сеть и не открывает игровой сокет: ни map.step, ни map.traverse
  expect(fetchMock).not.toHaveBeenCalled();
  expect(socket).not.toHaveBeenCalled();
});

it("пустая карта объясняет, что подготовка не завершена", () => {
  render(<MapPreview map={{ ...map, areas: [] }} />);
  expect(screen.getByText(/ещё не готова/)).toBeTruthy();
});
