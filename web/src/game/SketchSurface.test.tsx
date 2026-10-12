import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SketchSurface } from "./SketchSurface";
import type { Sketch } from "./map";

const sketch: Sketch = {
  shape: "open", cols: 3, rows: 2, party: [0, 0], mask: ["..#", "..."], walls: [],
  edges: [{ side: "e", start: 0, length: 1, meaning: "continuation" }, { side: "s", start: 1, length: 1, meaning: "obstacle" }],
  terrain: [{ kind: "stream", cells: [[0, 1]] }, { kind: "bridge", cells: [[0, 1]] }],
  exits: [{ name: "Мост", side: "e", at: 1, width: 2, kind: "gap", cells: [[2, 0], [2, 1]] }], features: [],
};

describe("SVG-поверхность эскиза", () => {
  it("clips floor, draws terrain and keeps continuation open", () => {
    const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="one" /></svg>);
    const svg = container.querySelector("svg")!;
    expect(svg.querySelectorAll("image,foreignObject")).toHaveLength(0);
    expect(svg.querySelector('[data-edge-meaning="continuation"][data-wall="true"]')).toBeNull();
    expect(svg.querySelector('[data-terrain="bridge"]')).not.toBeNull();
    expect(svg.querySelector("clipPath")?.children.length).toBe(5);
  });

  it("names defs per instance", () => {
    const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="a" /><SketchSurface sketch={sketch} idPrefix="b" /></svg>);
    const ids = [...container.querySelectorAll("[id]")].map((node) => node.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
