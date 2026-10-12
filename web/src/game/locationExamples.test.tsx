import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import field from "../../../docs/examples/location-maps/field-stream-bridge.json";
import temple from "../../../docs/examples/location-maps/temple-known.json";
import memory from "../../../docs/examples/location-maps/hero-memory.json";
import type { MapState as WireMapState } from "../lib/api.gen";
import { mapForDisplay, useMapWindow } from "./map";
import { LocationMapSvg } from "./LocationMap";
import MapWindow from "./MapWindow";
import { useGame } from "../stores/game";

describe("серверные примеры карты", () => {
  it("отрисовывает все клетки дороги и маску настоящего снимка", () => {
    const m = mapForDisplay(field as unknown as WireMapState);
    const { container } = render(<LocationMapSvg map={m.location_map!} idPrefix="field" />);
    expect(container.querySelectorAll('[data-terrain="road"] rect').length).toBeGreaterThan(10);
    expect(container.querySelector('[data-terrain="stream"]')).not.toBeNull();
    expect(container.querySelector('[data-terrain="bridge"]')).not.toBeNull();
    expect(temple.sketch.mask).toContainEqual(expect.stringContaining("#"));
    expect(JSON.stringify(memory)).not.toContain("demo-vault");
    expect(JSON.stringify(memory)).not.toContain("demo-crypt");
  });

  it("память не вызывает переход и подключённое окно отправляет выбранный проход", () => {
    const m = mapForDisplay(field as unknown as WireMapState);
    const onPassage = vi.fn();
    const surface = render(<LocationMapSvg map={m.location_map!} idPrefix="memory" onPassage={onPassage} />);
    const rememberedExit = surface.container.querySelector('[data-area-status="remembered"] [data-passage-ref]');
    if (rememberedExit) fireEvent.click(rememberedExit);
    expect(onPassage).not.toHaveBeenCalled();
    surface.unmount();
    const send = vi.fn(() => true);
    useMapWindow.setState({ open: false });
    useGame.setState({ playAs: null, socket: { send } as never });
    useMapWindow.getState().resetForViewer();
    useMapWindow.getState().receive(m);
    useMapWindow.setState({ open: true, tab: "around" });
    const { container } = render(<MapWindow />);
    const passage = container.querySelector('[data-area-status="here"] [data-passage-ref]')!;
    expect(passage).not.toBeNull();
    fireEvent.click(passage);
    fireEvent.click(screen.getByRole("button", { name: "Перейти" }));
    expect(send).toHaveBeenCalledWith("map.traverse", expect.objectContaining({ source_id: m.here!.id }));
    useMapWindow.setState({ open: false });
  });
});
