import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useDraft } from "./draft";
import { UnlocatedExitStrip } from "./MapWindow";
import type { MapState } from "./map";

const m: MapState = {
  here: { id: "hall", name: "Зал Мёртвых", description: null },
  around: [], party: [], places: [], links: [], bearings: {} as MapState["bearings"],
  exits: [
    { id: "cem", name: "Кладбище у мавзолея", via: null, bearing: null, visited: true },
    { id: "r2", name: "Восточная крипта", via: null, bearing: null, visited: true },
    { id: "r3", name: "Комната 3", via: null, bearing: null, visited: false },
  ],
  sketch: {
    shape: "room", cols: 7, rows: 7, party: [3, 3], walls: [], features: [], exits: [],
    book: true,
    unplaced_exits: [
      { name: "Кладбище у мавзолея", to: "cem" },
      { name: "Комната 2", to: "r2" },
      { name: "Комната 3", to: "r3" },
    ],
  },
};

afterEach(() => {
  cleanup();
  useDraft.setState({ text: "", campaignId: null });
});

describe("проходы без разметки на карте", () => {
  it("отображает каждый переход графически, отдельно от стен, с доступным действием", () => {
    useDraft.setState({ text: "", campaignId: null });
    render(<UnlocatedExitStrip m={m} />);
    expect(screen.getByRole("region", { name: "Проходы с неизвестным положением" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^Найти проход:/ })).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Восточная крипта" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Найти проход: Восточная крипта" }));
    expect(useDraft.getState().text).toContain("Ищу, где находится проход к месту «Восточная крипта».");
  });

  it("не показывает фиктивную карточку и не дублирует реальные двери на стене", () => {
    render(
      <UnlocatedExitStrip m={{
        ...m,
        sketch: {
          ...m.sketch!,
          exits: [{ name: "Восточная крипта", to: "r2", side: "e", at: 2, kind: "door" }],
          unplaced_exits: [...m.sketch!.unplaced_exits!, { name: "Неизвестный переход", to: null }],
        },
      }} />,
    );
    expect(screen.queryByRole("button", { name: "Восточная крипта" })).toBeNull();
    expect(screen.getByText("Неизвестный переход")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Неизвестный переход" })).toBeNull();
    expect(screen.getAllByRole("button", { name: /^Найти проход:/ })).toHaveLength(3);
  });
});
