import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LocationMap } from "./LocationMap";
import type { MapLocationPlan } from "./map";

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
