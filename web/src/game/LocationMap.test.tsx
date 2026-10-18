import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocationMap } from "./LocationMap";
import { SketchSurface } from "./SketchSurface";
import { useMapWindow, type MapLocationPlan, type MapState } from "./map";

const map: MapLocationPlan = {
  root_id: "root", here_id: "current", areas: [
    { id: "current", name: "Текущий", offset: [-6, -4], level: 0, status: "here", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
    { id: "remembered", name: "Память", offset: [0, -4], level: 0, status: "remembered", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
    { id: "hidden-level", name: "Скрыто", offset: [0, 0], level: -1, status: "remembered", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
  ],
};

it("рисует твёрдую мебель без повторной заливки стены", () => {
  const sketch = { ...map.areas[0].sketch, walls: [[0, 0], [1, 1]] as [number, number][],
    features: [{ id: "table", name: "Стол", kind: "furniture" as const, solid: true, cells: [[0, 0, 0, 0]] }] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="solid-test" /></svg>);
  expect(container.querySelector('[data-feature-solid="true"] title')?.textContent).toBe("Стол");
  expect(container.querySelectorAll('rect[fill="var(--tf-map-wall, #111)"]')).toHaveLength(1);
  expect(sketch.walls).toEqual([[0, 0], [1, 1]]);
});

it("выбирает силуэт детали по visual_key, независимо от её имени", () => {
  const sketch = { ...map.areas[0].sketch, features: [
    { id: "a", name: "Произвольное имя", kind: "furniture" as const, visual_key: "feature:bed", cells: [[0, 0, 0, 1]] },
    { id: "b", name: "Кровать", kind: "object" as const, visual_key: "feature:barrel", cells: [[1, 0, 1, 0]] },
  ] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="artwork" /></svg>);
  expect(container.querySelector('[data-feature-id="a"] [data-feature-form="bed"]')).not.toBeNull();
  expect(container.querySelector('[data-feature-id="b"] [data-feature-form="barrel"]')).not.toBeNull();
});

it("объединяет клетки Г-образной стойки и не рисует предмет в пустом углу", () => {
  const sketch = { ...map.areas[0].sketch, features: [
    { id: "counter", name: "Стойка", kind: "furniture" as const, visual_key: "feature:counter", solid: true,
      cells: [[0, 0, 1, 0], [1, 0, 1, 1]] },
  ] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="footprint" /></svg>);
  const bodies = container.querySelectorAll('[data-feature-id="counter"] [data-feature-body]');
  expect(bodies).toHaveLength(1);
  expect(bodies[0].getAttribute("data-footprint-area")).toBe("3");
  expect(bodies[0].tagName.toLowerCase()).toBe("path");
  expect(sketch.features[0].cells).toEqual([[0, 0, 1, 0], [1, 0, 1, 1]]);
});

it("не интерпретирует неизвестный visual_key как URL или имя встроенного свойства", () => {
  const sketch = { ...map.areas[0].sketch, features: [
    { id: "unknown", name: "Стол", kind: "furniture" as const, visual_key: "toString", cells: [[0, 0, 0, 0]] },
    { id: "url", name: "Ящик", kind: "object" as const, visual_key: "https://example.invalid/a.svg", cells: [[1, 0, 1, 0]] },
  ] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="fallback" /></svg>);
  expect(container.querySelector('[data-feature-id="unknown"] [data-feature-form="table"]')).not.toBeNull();
  expect(container.querySelector('[data-feature-id="url"] [data-feature-form="crate"]')).not.toBeNull();
  expect(container.querySelector("image, img, use")).toBeNull();
});

it("отличает светящийся мох и звериную лежку от огня и кровати", () => {
  const sketch = { ...map.areas[0].sketch, features: [
    { id: "lichen", name: "Мох", kind: "light" as const, visual_key: "feature:lichen", cells: [[0, 0, 0, 0]] },
    { id: "nest", name: "Лёжка", kind: "nature" as const, visual_key: "feature:nest", cells: [[1, 0, 1, 0]] },
  ] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="natural-props" /></svg>);
  expect(container.querySelector('[data-feature-id="lichen"] [data-feature-form="lichen"]')).not.toBeNull();
  expect(container.querySelector('[data-feature-id="nest"] [data-feature-form="nest"]')).not.toBeNull();
  expect(container.querySelector('[data-feature-form="torch"], [data-feature-form="bed"]')).toBeNull();
});

it("оставляет иконку сущности и опасности на занятой клетке составной детали", () => {
  const ring = [[0, 0, 2, 0], [0, 2, 2, 2], [0, 1, 0, 1], [2, 1, 2, 1]];
  const sketch = { ...map.areas[0].sketch, cols: 3, rows: 3, features: [
    { id: "chest", name: "Сундук", kind: "object" as const, entity_type: "item" as const,
      visual_key: "item:chest", cells: ring },
    { id: "hazard", name: "Опасность", kind: "hazard" as const, cells: ring },
  ] };
  const { container } = render(<svg><SketchSurface sketch={sketch} idPrefix="ring-icons" /></svg>);
  for (const id of ["chest", "hazard"]) {
    const glyph = container.querySelector(`[data-feature-id="${id}"] svg`)!;
    const x = Math.floor(Number(glyph.getAttribute("x")) + .35);
    const y = Math.floor(Number(glyph.getAttribute("y")) + .35);
    expect(x === 0 || x === 2 || y === 0 || y === 2).toBe(true);
  }
});

describe("единая карта комплекса", () => {
  it("рисует текущий и запомненный участок в общих offsets", () => {
    const { container } = render(<LocationMap map={map} />);
    expect(container.querySelectorAll('[data-area-status="remembered"]')).toHaveLength(1);
    expect(container.querySelector('[data-area-id="remembered"]')?.getAttribute("transform")).toBe("translate(0 -4)");
    expect(screen.getByRole("button", { name: /уровень -1/i })).not.toBeNull();
  });

  it("приглушает подготовленный, но ещё не исследованный участок", () => {
    const prepared = { ...map.areas[1], id: "prepared", status: "prepared" as const };
    const { container } = render(<LocationMap map={{ ...map, areas: [map.areas[0], prepared] }} />);
    expect(container.querySelector('[data-area-status="prepared"]')?.getAttribute("opacity")).toBe("0.22");
  });
});

describe("подход к проходу", () => {
  it("переводит клетки прохода в механику от того же строя, что и клики и токены", () => {
    const stepTo = vi.fn();
    useMapWindow.setState({ stepTo });
    const exit = { name: "Дверь", kind: "door" as const, state: "closed" as const, side: "e" as const, at: 1, cells: [[1, 1]] as [number, number][], passage_ref: "p_arch" };
    const plan: MapLocationPlan = { ...map, areas: [{ ...map.areas[0], sketch: { ...map.areas[0].sketch, party: [0, 0], exits: [exit] } }] };
    const live = { ...plan.areas[0].sketch, party: [1, 0] as [number, number] };
    const { container } = render(<LocationMap map={plan} m={{ sketch: live, scene_view: [] } as unknown as MapState} />);
    const passage = container.querySelector('[data-passage-ref="p_arch"]')!;
    expect(passage.classList.contains("is-picked")).toBe(false);
    fireEvent.click(passage);
    expect(passage.classList.contains("is-picked")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Подойти" }));
    expect(stepTo).toHaveBeenCalledWith({ near: [[0, 1]] });
  });

  it("проходы рендерятся поверх кликабельных клеток пола и текущая комната идет последней", () => {
    const exit = { name: "Дверь", kind: "door" as const, state: "open" as const, side: "e" as const, at: 0, cells: [[0, 0]] as [number, number][], passage_ref: "p_door" };
    const plan: MapLocationPlan = { ...map, areas: [{ ...map.areas[0], sketch: { ...map.areas[0].sketch, exits: [exit] } }, map.areas[1]] };
    const { container } = render(<LocationMap map={plan} m={{ sketch: plan.areas[0].sketch, scene_view: [] } as unknown as MapState} />);
    const currentGroup = container.querySelector('[data-area-status="here"]')!;
    const passage = currentGroup.querySelector('[data-passage-ref="p_door"]')!;
    const cellRects = currentGroup.querySelectorAll('rect[fill="transparent"]');
    expect(cellRects.length).toBeGreaterThan(0);
    // Проход должен следовать в DOM после клеток пола (z-order выше)
    const allChildren = Array.from(currentGroup.querySelectorAll('*'));
    expect(allChildren.indexOf(passage)).toBeGreaterThan(allChildren.indexOf(cellRects[0]));

    // Текущая комната должна рендериться после запомненной
    const areaGroups = Array.from(container.querySelectorAll('g[data-area-id]'));
    expect(areaGroups[areaGroups.length - 1].getAttribute('data-area-status')).toBe('here');
  });
});
