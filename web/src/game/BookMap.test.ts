import { describe, expect, it } from "vitest";
import { roomRects, tokenSize } from "./BookMap";
import type { MapBook } from "./map";

const book: MapBook = {
  module_id: "mod1",
  map_id: "map1",
  name: "Склеп",
  grid: { cols: 10, rows: 8, left: 0, top: 0, right: 1, bottom: 0.8 },
  here: "1",
  rooms: [{ number: "1", x: 0.2, y: 0.3, status: "here", name: "Зал", cells: [[0, 0, 3, 5]] }],
  tokens: [],
};

describe("карта книги", () => {
  it("клетки комнаты превращаются в прямоугольник рисунка", () => {
    // 10 колонок на 1000 единиц ширины, 8 строк на 80% высоты 800
    expect(roomRects(book, [[0, 0, 3, 5]], 1000, 800)).toEqual([{ x: 0, y: 0, w: 400, h: 480 }]);
    expect(roomRects({ ...book, grid: null }, [[0, 0, 1, 1]], 1000, 800)).toEqual([]);
  });

  it("значок — в клетку сетки книги, без сетки — 3% ширины", () => {
    expect(tokenSize(book, 1000)).toBe(100);
    expect(tokenSize({ ...book, grid: null }, 1000)).toBe(30);
  });
});
