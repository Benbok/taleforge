import { describe, expect, it, vi } from "vitest";
import { useGame } from "../stores/game";
import {
  freeCell,
  GRID_R,
  layoutGrid,
  layoutPlaces,
  mapEvent,
  useMapWindow,
  type MapHero,
  type MapState,
  type MapThing,
} from "./map";

const empty: MapState = { here: null, around: [], exits: [], places: [], links: [], bearings: {} as MapState["bearings"] };

describe("карта", () => {
  it("сторона света задаёт клетку: север вверху, восток справа; зона — число клеток", () => {
    const thing = (id: string, zone: MapThing["zone"], bearing: MapThing["bearing"]): MapThing => ({
      id, name: id, type: "creature", zone, zone_name: zone, bearing,
    });
    const g = layoutGrid({ ...empty, around: [thing("n", "near", "n"), thing("e", "melee", "e"), thing("f", "far", "s")] });
    const at = (id: string) => g.things.find((x) => x.item.id === id)!;
    expect([at("n").col, at("n").row]).toEqual([0, -6]); // 30 футов на север
    expect([at("e").col, at("e").row]).toEqual([1, 0]); // вплотную на восток
    expect([at("f").col, at("f").row]).toEqual([0, 12]); // далеко — у края
  });

  it("двое в одной точке встают в соседние клетки, никто не делит клетку", () => {
    const hero: MapHero = { id: "h1", name: "Воин", mine: true, zone: "near", bearing: "e", elevation: "ground", cover: "none", down: false };
    const m = (id: string): MapThing => ({ id, name: id, type: "creature", zone: "near", zone_name: "близко", bearing: "e" });
    const g = layoutGrid({ ...empty, party: [hero], around: [m("m1"), m("m2")] });
    const cells = [...g.heroes, ...g.things].map((x) => `${x.col},${x.row}`);
    expect(new Set(cells).size).toBe(3);
    expect(cells[0]).toBe("6,0"); // герой первым занял свою точку
    for (const c of cells.slice(1)) {
      const [col, row] = c.split(",").map(Number);
      expect(Math.max(Math.abs(col - 6), Math.abs(row))).toBe(1); // соседи — вплотную к точке
    }
  });

  it("места раскладываются по числу переходов от героя, несвязанные — последним столбцом", () => {
    const place = (id: string, parent_id: string | null = null) => ({ id, name: id, parent_id, status: "known" as const });
    const laid = layoutPlaces({
      here: { id: "sq", name: "sq", description: null },
      places: [place("sq"), place("docks"), place("shop", "sq"), place("cellar", "shop"), place("far")],
      links: [{ a: "docks", b: "sq", label: null }],
    });
    const col = Object.fromEntries(laid.map((p) => [p.place.id, p.col]));
    expect(col).toEqual({ sq: 0, docks: 1, shop: 1, cellar: 2, far: 3 });
  });

  it("открытая карта перезапрашивается после хода мастера, закрытая — нет", () => {
    const send = vi.fn(() => true);
    useGame.setState({ socket: { send } as never });
    mapEvent("scene.updated", {});
    expect(send).not.toHaveBeenCalled();
    useMapWindow.getState().show();
    expect(send).toHaveBeenCalledWith("map.get");
    mapEvent("scene.updated", {});
    expect(send).toHaveBeenCalledTimes(2);
    mapEvent("map.state", { ...empty, here: { id: "x", name: "Площадь", description: null } });
    expect(useMapWindow.getState().data?.here?.name).toBe("Площадь");
    expect(useMapWindow.getState().loading).toBe(false);
  });

  it("герои в строю стоят у центра в разных клетках; выходы — у края; область не занимает клетку", () => {
    const hero = (id: string): MapHero => ({ id, name: id, mine: false, zone: null, bearing: null, elevation: "ground", cover: "none", down: false });
    const g = layoutGrid({
      ...empty,
      party: [hero("a"), hero("b"), hero("c")],
      exits: [{ id: "x", name: "Дверь", via: null, bearing: "w", visited: true }],
      areas: [{ id: "fog", name: "Туман", zone: "melee", bearing: null, radius_ft: 10 }],
    });
    expect([g.heroes[0].col, g.heroes[0].row]).toEqual([0, 0]);
    expect(new Set(g.heroes.map((h) => `${h.col},${h.row}`)).size).toBe(3);
    expect(g.heroes.every((h) => Math.max(Math.abs(h.col), Math.abs(h.row)) <= 1)).toBe(true);
    expect([g.exits[0].col, g.exits[0].row]).toEqual([-GRID_R, 0]);
    expect(g.areas).toHaveLength(1);
  });

  it("свободная клетка ищется по кольцам и не выходит за схему", () => {
    const taken = new Set(["0,0", "1,0", "0,1"]);
    expect(freeCell(0, 0, taken)).toEqual([0, -1]);
    expect(freeCell(GRID_R + 5, 0, new Set())).toEqual([GRID_R, 0]);
  });
});
