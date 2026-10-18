import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SketchSurface } from "./SketchSurface";
import type { Sketch, SketchFeature } from "./map";

const torch = (id: string, c: number, r: number): SketchFeature => ({ id, name: "Torch", kind: "light", visual_key: "feature:torch", cells: [[c, r]] });
const room: Sketch = { shape: "room", environment: "indoor", cols: 5, rows: 5, party: [2, 2], walls: [], exits: [], features: [] };

function paint(sketch: Sketch) {
  return render(<svg><SketchSurface sketch={sketch} idPrefix="mount" /></svg>).container;
}

describe("wall torch placement", () => {
  it.each([
    ["n", 2, 0, 2.5, .24, 0], ["e", 4, 2, 4.76, 2.5, 90],
    ["s", 2, 4, 2.5, 4.76, 180], ["w", 0, 2, .24, 2.5, 270],
  ])("mounts a %s wall bracket inward and centers its glow on the flame", (side, c, r, x, y, angle) => {
    const container = paint({ ...room, features: [torch("wall", Number(c), Number(r))] });
    const mount = container.querySelector('[data-wall-torch]');
    expect(mount).not.toBeNull();
    expect(mount!.getAttribute("data-wall-side")).toBe(side);
    expect(mount!.getAttribute("transform")).toBe(`translate(${x} ${y}) rotate(${angle})`);
    const light = container.querySelector('[data-light-source="wall"]')!;
    expect(Number(light.getAttribute("cx"))).toBe(x);
    expect(Number(light.getAttribute("cy"))).toBe(y);
    expect(mount!.closest('[clip-path="url(#mount-feature-0-0)"]')).not.toBeNull();
  });

  it("uses a recessed actual mask wall instead of the rectangular room bounds", () => {
    const container = paint({ ...room, mask: ["#....", "#....", ".....", ".....", "....."], features: [torch("step", 1, 1)] });
    const mount = container.querySelector('[data-wall-torch]')!;
    expect(mount).not.toBeNull();
    expect(mount.getAttribute("data-wall-side")).toBe("w");
    expect(mount.getAttribute("transform")).toBe("translate(1.24 1.5) rotate(270)");
  });

  it("avoids door widths and chooses another real wall at a doorway corner", () => {
    const container = paint({ ...room, exits: [{ name: "Door", side: "n", at: 0, width: 3, kind: "door" }], features: [torch("corner", 0, 0), torch("doorway", 2, 0)] });
    expect(container.querySelector('[data-feature-id="corner"] [data-wall-torch]')?.getAttribute("data-wall-side")).toBe("w");
    expect(container.querySelector('[data-feature-id="doorway"] [data-wall-torch]')).toBeNull();
  });

  it.each([
    { environment: "outdoor" }, { shape: "open" as const }, { shape: "street" as const }, { material: "water" },
    { edges: [{ side: "n" as const, start: 1, length: 3, meaning: "continuation" as const }] },
  ])("does not invent wall mounts for open boundaries: %j", (change) => {
    const container = paint({ ...room, ...change, features: [torch("outside", 2, 0)] });
    expect(container.querySelector('[data-wall-torch]')).toBeNull();
    const light = container.querySelector('[data-light-source="outside"]')!;
    expect(light.getAttribute("cx")).toBe("2.5");
    expect(light.getAttribute("cy")).toBe("0.5");
  });

  it("preserves server-supplied GM artwork without hidden halos or wall mounts", () => {
    const container = paint({ ...room, features: [torch("interior", 2, 2), { ...torch("secret", 0, 2), hidden: true }] });
    expect(container.querySelector('[data-wall-torch]')).toBeNull();
    expect(container.querySelector('[data-light-source="secret"]')).toBeNull();
    expect(container.querySelector('[data-feature-id="secret"] [data-feature-form="torch"]')).not.toBeNull();
    expect(container.querySelector('[data-feature-id="secret"] title')?.textContent).toBe("Torch");
    expect(container.querySelector('[data-light-source="interior"]')?.getAttribute("cx")).toBe("2.5");
  });
});
