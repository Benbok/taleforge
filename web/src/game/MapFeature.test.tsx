import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapFeature } from "./MapFeature";
import type { SketchFeature } from "./map";

const tree: SketchFeature = { id: "oak-17", name: "Oak", kind: "nature", visual_key: "feature:tree", cells: [[0, 0]] };
const artwork = (container: HTMLElement) => container.querySelector('g[clip-path]')!.innerHTML;

describe("MapFeature artwork", () => {
  it("keeps organic variation stable through rerenders and names while varying different objects", () => {
    const { container, rerender } = render(<svg><MapFeature feature={tree} idPrefix="tree" /></svg>);
    const original = artwork(container);
    rerender(<svg><MapFeature feature={{ ...tree, name: "Ancient oak" }} idPrefix="tree" /></svg>);
    expect(artwork(container)).toBe(original);
    rerender(<svg><MapFeature feature={{ ...tree, id: "oak-18" }} idPrefix="tree" /></svg>);
    expect(artwork(container)).not.toBe(original);
    rerender(<svg><MapFeature feature={tree} idPrefix="tree" /></svg>);
    expect(artwork(container)).toBe(original);
  });

  it("varies occupied cells without reshuffling when cell order or SVG prefix changes", () => {
    const grove = { ...tree, cells: [[0, 0], [1, 0]] };
    const { container, rerender } = render(<svg><MapFeature feature={grove} idPrefix="grove" /></svg>);
    const cellArt = (position: string) => [...container.querySelectorAll('g[clip-path] > g > g')]
      .find((node) => node.getAttribute("transform")?.startsWith(position))!.innerHTML;
    const first = cellArt("translate(0.5 0.5)"), second = cellArt("translate(1.5 0.5)");
    expect(second).not.toBe(first);
    rerender(<svg><MapFeature feature={{ ...grove, cells: [[1, 0], [0, 0]] }} idPrefix="new-instance" /></svg>);
    expect(cellArt("translate(0.5 0.5)")).toBe(first);
    expect(cellArt("translate(1.5 0.5)")).toBe(second);
  });

  it("keeps holes and disconnected occupied groups in the artwork clips", () => {
    const ring: SketchFeature = { ...tree, visual_key: "feature:table", cells: [[0, 0, 2, 0], [0, 1], [2, 1], [0, 2, 2, 2], [5, 0]] };
    const { container } = render(<svg><MapFeature feature={ring} idPrefix="ring" /></svg>);
    const clips = [...container.querySelectorAll("clipPath")];
    expect(clips).toHaveLength(2);
    const ringPath = clips[0].querySelector("path")!;
    expect(ringPath.getAttribute("fill-rule")).toBe("evenodd");
    expect(ringPath.getAttribute("d")?.match(/M/g)).toHaveLength(2);
    const bodies = [...container.querySelectorAll('[data-feature-body="true"]')];
    expect(bodies.map((node) => node.getAttribute("data-footprint-area"))).toEqual(["8", "1"]);
    clips.forEach((clip, index) => {
      expect(clip.querySelector("path")?.getAttribute("d")).toBe(bodies[index].getAttribute("d"));
      expect(container.querySelector(`g[clip-path="url(#${clip.id})"]`)?.getAttribute("pointer-events")).toBe("none");
    });
  });

  it("opens bound feature actions by keyboard and click, leaving decoration unfocusable", () => {
    const onFeature = vi.fn();
    const { container, rerender } = render(<svg><MapFeature feature={{ ...tree, entity_id: "entity-4" }} idPrefix="action" onFeature={onFeature} /></svg>);
    const button = container.querySelector('[role="button"]')!;
    expect(button).not.toBeNull();
    expect(button.getAttribute("aria-label")).toBe("Oak");
    expect(button.getAttribute("tabindex")).toBe("0");
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.keyDown(button, { key: " " });
    fireEvent.keyDown(button, { key: "Escape" });
    fireEvent.click(button);
    expect(onFeature).toHaveBeenCalledTimes(3);
    expect(onFeature).toHaveBeenLastCalledWith("entity-4", "Oak");
    rerender(<svg><MapFeature feature={tree} idPrefix="action" onFeature={onFeature} /></svg>);
    expect(container.querySelector('[role="button"], [tabindex]')).toBeNull();
  });

  it("chooses defaults from trusted kind instead of names or unknown visual keys", () => {
    const { container } = render(<svg><MapFeature feature={{ ...tree, name: "feature:chest", visual_key: "javascript:alert(1)" }} idPrefix="safe" /></svg>);
    expect(container.querySelector('[data-feature-form]')?.getAttribute("data-feature-form")).toBe("shrub");
    expect(container.querySelector("image, foreignObject, script")).toBeNull();
  });
});
