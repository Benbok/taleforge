import { describe, expect, it } from "vitest";
import { exitCells, sketchFrame, type Sketch } from "./map";

describe("геометрия эскиза", () => {
  it("не разрешает клетки вне маски и использует клетки широкого прохода", () => {
    const sk: Sketch = {
      shape: "room", cols: 3, rows: 3, party: [1, 1], walls: [], exits: [], features: [],
      mask: ["###", "#..", "#.."],
    };
    expect(sketchFrame(sk).allowed(-1, -1)).toBe(false);
    expect(sketchFrame(sk).allowed(0, 0)).toBe(true);
    expect(exitCells(sk, { name: "Край", kind: "gap", side: "e", at: 1, width: 2, cells: [[2, 1], [2, 2]] })).toEqual([[1, 0], [1, 1]]);
  });
});
