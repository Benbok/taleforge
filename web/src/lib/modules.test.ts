import { describe, expect, it } from "vitest";
import { anyBusy, placeMark, unplaced } from "./modules";

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
});
