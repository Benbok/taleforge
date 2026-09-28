import { describe, expect, it, vi } from "vitest";
import { sideEffects } from "../lib/useGameSocket";
import type { Envelope } from "../lib/types";
import { useToasts } from "../stores/toasts";
import { secondsLeft } from "./Composer";

const env = (type: string, payload: object = {}): Envelope => ({ type, campaign_id: "c1", seq: null, payload: payload as Record<string, unknown> });

describe("игровой экран", () => {
  it("ошибка сервера показывается причиной, а смена хода перезапрашивает кнопки", () => {
    const send = vi.fn(() => true);
    sideEffects(env("error", { code: "forbidden", message: "инструменты мастера доступны только месту мастера" }), { send });
    expect(useToasts.getState().items.at(-1)?.text).toBe("инструменты мастера доступны только месту мастера");
    expect(send).not.toHaveBeenCalled();
    sideEffects(env("turn.changed", { turn: null }), { send });
    expect(send).toHaveBeenCalledWith("actions.get");
  });

  it("таймер хода считает секунды до конца", () => {
    expect(secondsLeft(null, 0)).toBeNull();
    expect(secondsLeft(100, 70_000)).toBe(30);
    expect(secondsLeft(100, 120_000)).toBe(0);
  });

  it("статус и отмена реплики перезапрашивают кнопки", () => {
    const send = vi.fn(() => true);
    sideEffects(env("message.state", { ids: ["m1"], state: "answered" }), { send });
    sideEffects(env("message.withdrawn", { id: "m1", seq: 1 }), { send });
    expect(send).toHaveBeenCalledTimes(2);
  });
});
