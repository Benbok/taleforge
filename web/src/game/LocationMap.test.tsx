import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocationMap } from "./LocationMap";
import { useMapWindow, type MapLocationPlan, type MapState } from "./map";

const map: MapLocationPlan = {
  root_id: "root", here_id: "current", areas: [
    { id: "current", name: "Текущий", offset: [-6, -4], level: 0, status: "here", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
    { id: "remembered", name: "Память", offset: [0, -4], level: 0, status: "remembered", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
    { id: "hidden-level", name: "Скрыто", offset: [0, 0], level: -1, status: "remembered", revision: 1, sketch: { shape: "open", cols: 2, rows: 2, party: [0, 0], walls: [], exits: [], features: [] } },
  ],
};

describe("единая карта комплекса", () => {
  it("рисует текущий и запомненный участок в общих offsets", () => {
    const { container } = render(<LocationMap map={map} />);
    expect(container.querySelectorAll('[data-area-status="remembered"]')).toHaveLength(1);
    expect(container.querySelector('[data-area-id="remembered"]')?.getAttribute("transform")).toBe("translate(0 -4)");
    expect(screen.getByRole("button", { name: /уровень -1/i })).not.toBeNull();
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
    fireEvent.click(container.querySelector('[data-passage-ref="p_arch"]')!);
    fireEvent.click(screen.getByRole("button", { name: "Подойти" }));
    expect(stepTo).toHaveBeenCalledWith({ near: [[0, 1]] });
  });
});
