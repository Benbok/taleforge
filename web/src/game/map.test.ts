import { describe, expect, it, vi } from "vitest";
import { useGame } from "../stores/game";
import { areaPx, layoutPlaces, mapEvent, placeAround, placeParty, useMapWindow, type MapHero, type MapState } from "./map";

const empty: MapState = { here: null, around: [], exits: [], places: [], links: [], bearings: {} as MapState["bearings"] };

describe("карта", () => {
  it("сторона света задаёт угол: север вверху, восток справа; соседи расходятся", () => {
    const [n, e, n2] = placeAround(
      [
        { id: "a", bearing: "n" as const },
        { id: "b", bearing: "e" as const },
        { id: "c", bearing: "n" as const },
      ],
      () => 100,
    );
    expect(n.x).toBeCloseTo(200);
    expect(n.y).toBeCloseTo(100);
    expect(e.x).toBeCloseTo(300);
    expect(Math.hypot(n2.x - n.x, n2.y - n.y)).toBeGreaterThan(55);
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

  it("герои в строю стоят кучкой у центра, вышедшие — на своих кольцах; область не больше схемы", () => {
    const hero = (id: string, zone: MapHero["zone"] = null, bearing: MapHero["bearing"] = null): MapHero => ({
      id, name: id, mine: false, zone, bearing, elevation: "ground", cover: "none", down: false,
    });
    const [a, b, c] = placeParty([hero("a"), hero("b"), hero("c", "near", "e")]);
    expect(Math.hypot(a.x - 200, a.y - 200)).toBeCloseTo(22);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(30);
    expect(c.x).toBeCloseTo(305);
    expect(areaPx(10)).toBe(35);
    expect(areaPx(120)).toBe(90);
  });
});
