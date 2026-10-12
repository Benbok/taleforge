import { describe, expect, it, vi } from "vitest";
import { mapEvent, useMapWindow } from "./map";
import { useGame } from "../stores/game";

describe("переход по карте", () => {
  it("при смене героя очищает карту и игнорирует ответ прежнего зрителя", () => {
    useMapWindow.setState({ open: false });
    useGame.setState({ playAs: null, socket: { send: vi.fn(() => true) } as never });
    useMapWindow.getState().traverseTo("old-passage", "old-room");
    const oldRequest = useMapWindow.getState().traverse.request_id;
    useGame.getState().setPlayAs("second-seat");
    expect(useMapWindow.getState().data).toBeNull();
    expect(useMapWindow.getState().traverse.busy).toBe(false);
    mapEvent({ type: "map.traverse.result", payload: { request_id: oldRequest, ok: true } } as never);
    mapEvent({ type: "map.state", payload: { as_seat: null, request_id: "old-map" } } as never);
    expect(useMapWindow.getState().data).toBeNull();
    useGame.getState().setPlayAs(null);
  });
  it("отправляет один запрос и не двигает карту оптимистически", () => {
    const send = vi.fn(() => true);
    useGame.setState({ socket: { send } as never, playAs: null });
    useMapWindow.getState().resetForViewer();
    useMapWindow.getState().traverseTo("p_cell", "hall");
    useMapWindow.getState().traverseTo("p_cell", "hall");
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("map.traverse", expect.objectContaining({ passage_ref: "p_cell", source_id: "hall", request_id: expect.any(String) }));
    expect(useMapWindow.getState().traverse.busy).toBe(true);
  });

  it("игнорирует устаревший ответ и показывает причину отказа", () => {
    const send = vi.fn(() => true);
    useGame.setState({ socket: { send } as never, playAs: null });
    useMapWindow.getState().resetForViewer();
    useMapWindow.getState().traverseTo("p_cell", "hall");
    const request_id = useMapWindow.getState().traverse.request_id!;
    mapEvent({ type: "map.traverse.result", payload: { request_id: "old", ok: false, moved: false, reason: "старый" } } as never);
    expect(useMapWindow.getState().traverse.busy).toBe(true);
    mapEvent({ type: "map.traverse.result", payload: { request_id, ok: true, moved: false, reason: "дверь закрыта" } } as never);
    expect(useMapWindow.getState().traverse.busy).toBe(false);
    expect(useMapWindow.getState().traverse.reason).toBe("дверь закрыта");
  });
});
