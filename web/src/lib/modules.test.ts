import { describe, expect, it } from "vitest";
import {
  addRect,
  anyBusy,
  cellAt,
  inRoom,
  placeMark,
  toggleBlocked,
  unplaced,
} from "./modules";

describe("готовые приключения", () => {
  it("номер ставится в точку щелчка и заменяет прежнюю отметку", () => {
    const marks = placeMark([{ number: "1", x: 0.1, y: 0.1 }], "1", 0.5, 1.2);
    expect(marks).toEqual([{ number: "1", x: 0.5, y: 1 }]);
    expect(unplaced(["1", "2", "3"], marks)).toEqual(["2", "3"]);
  });

  it("экран ждёт сервер, пока идёт разбор книги или карты", () => {
    expect(anyBusy({ status: "review", map_list: [] })).toBe(false);
    expect(anyBusy({ status: "translating", map_list: [] })).toBe(true);
    const map = {
      id: "m",
      name: "",
      location_id: null,
      marks: [],
      status: "reading" as const,
    };
    expect(anyBusy({ status: "review", map_list: [map] })).toBe(true);
  });

  it("сетка: клетка под щелчком, пол комнаты и занятые клетки", () => {
    const grid = {
      cols: 10,
      rows: 4,
      left: 0.1,
      top: 0,
      right: 0.9,
      bottom: 1,
    };
    expect(cellAt(grid, 0.05, 0.5)).toBeNull();
    expect(cellAt(grid, 0.15, 0.3)).toEqual([0, 1]);
    let room = addRect({ number: "1", x: 0.2, y: 0.2 }, [3, 2], [1, 0]);
    expect(room.cells).toEqual([[1, 0, 3, 2]]);
    expect(inRoom(room, [2, 1])).toBe(true);
    room = toggleBlocked(room, [2, 1]);
    expect(room.blocked).toEqual([[2, 1]]);
    expect(toggleBlocked(room, [9, 3])).toBe(room);
    expect(toggleBlocked(room, [2, 1]).blocked).toEqual([]);
    // номер переставили — клетки комнаты остались
    expect(placeMark([room], "1", 0.5, 0.5)[0].cells).toEqual([[1, 0, 3, 2]]);
  });
});
