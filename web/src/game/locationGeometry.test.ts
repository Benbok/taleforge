import { describe, expect, it } from "vitest";
import { exitSegments, knownBounds, localToPlan, mechanicalToPlan, overviewBounds, planToMechanical, surfaceGeometry } from "./locationGeometry";
import type { MapKnownArea, MapLocationPlan } from "./map";

const area = (id: string, offset: [number, number], level = 0, mask?: string[]): MapKnownArea => ({
  id, name: id, offset, level, status: "remembered", revision: 1, sketch: {
    shape: "open", cols: 6, rows: 6, party: [1, 1], walls: [], exits: [], features: [], mask,
  },
});

describe("координаты композиции", () => {
  it("сохраняет отрицательные offsets и механические координаты", () => {
    const a = area("a", [-6, -4]);
    expect(localToPlan(a, [3, 1])).toEqual([-3, -3]);
    expect(mechanicalToPlan(a, [2, 2], [1, -1])).toEqual([-3, -3]);
    expect(planToMechanical(a, [2, 2], [-3, -3])).toEqual([1, -1]);
  });

  it("не смешивает уровни и неизвестные участки", () => {
    const plan: MapLocationPlan = { root_id: "r", here_id: "a", areas: [area("a", [0, 0]), area("b", [6, 0], -1)] };
    expect(knownBounds(plan, 0)).toEqual({ minX: 0, minY: 0, maxX: 6, maxY: 6 });
    expect(knownBounds(plan, 1)).toBeNull();
  });

  it("центрирует обзорную область с минимальным масштабом и отступами", () => {
    const bounds = { minX: 0, minY: 0, maxX: 6, maxY: 6 };
    const ov = overviewBounds(bounds, 18, 12, 2);
    expect(ov).toEqual({ minX: -6, minY: -3, maxX: 12, maxY: 9 });
    expect(ov!.maxX - ov!.minX).toBe(18);
    expect(ov!.maxY - ov!.minY).toBe(12);
    expect(overviewBounds(null)).toBeNull();
  });

  it("строит контур отверстия по клетке L-маски", () => {
    const a = area("l", [0, 0], 0, ["####", "....", "####"]);
    const geometry = surfaceGeometry(a);
    expect(geometry.contours.some((s) => s.from[1] === 2 && s.to[1] === 2 && Math.min(s.from[0], s.to[0]) === 3)).toBe(true);
    expect(exitSegments(a, { name: "выход", side: "n", at: 0, kind: "gap", cells: [[3, 2]] })).toEqual([
      { from: [3, 2], to: [4, 2] },
    ]);
  });
});
