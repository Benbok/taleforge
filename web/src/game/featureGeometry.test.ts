import { describe, expect, it } from "vitest";
import { featureFootprints } from "./featureGeometry";

function signedArea(path: string): number {
  return path.split("Z").reduce((area, loop) => {
    const points = [...loop.matchAll(/[ML](-?\d+) (-?\d+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    return area + points.reduce((sum, p, i) => {
      const next = points[(i + 1) % points.length];
      return sum + p[0] * next[1] - next[0] * p[1];
    }, 0) / 2;
  }, 0);
}

describe("occupied feature outlines", () => {
  it("deduplicates overlaps without filling the empty corner of an L", () => {
    const [shape] = featureFootprints([[0, 0, 1, 0], [1, 0, 1, 1]]);
    expect(shape.cells).toHaveLength(3);
    expect(signedArea(shape.path)).toBe(3);
    expect([shape.width, shape.height]).toEqual([2, 2]);
  });
  it("keeps the central walkway open inside a ring of furniture", () => {
    const [shape] = featureFootprints([[0, 0, 2, 0], [0, 2, 2, 2], [0, 1, 0, 1], [2, 1, 2, 1]]);
    expect(shape.cells).toHaveLength(8);
    expect(shape.path.match(/M/g)).toHaveLength(2);
    expect(signedArea(shape.path)).toBe(8);
  });
  it("draws diagonally touching objects separately", () => {
    const shapes = featureFootprints([[0, 0, 0, 0], [1, 1, 1, 1]]);
    expect(shapes).toHaveLength(2);
    expect(shapes.map((shape) => signedArea(shape.path))).toEqual([1, 1]);
    expect(featureFootprints([])).toEqual([]);
  });
});
