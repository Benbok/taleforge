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
});

describe("герой", () => {
  it("лист обновляется событием сервера и сбрасывает старые разборы", async () => {
    const { useGame } = await import("../stores/game");
    const g = useGame.getState;
    g().reset();
    g().setSheet({ id: "ch1", name: "Бран", class_name: "Воин", resources: { hp: 12 } } as never);
    g().apply(env("stat.explained", { stat: "ac", character_id: "ch1", value: 16, parts: [] }));
    expect(g().explained.ac.value).toBe(16);
    g().apply(env("character.sheet", { character: { id: "ch1", name: "Бран", resources: { hp: 5 } } }));
    expect(g().sheet?.resources.hp).toBe(5);
    expect(g().sheet?.class_name).toBe("Воин"); // имя класса из REST сохраняется
    expect(g().explained).toEqual({});
  });

  it("свой герой — живой на месте зрителя, быстрое действие без права — с причиной", async () => {
    const { myHero } = await import("./hero");
    const { sendQuick } = await import("./quick");
    const { useGame } = await import("../stores/game");
    const h = (id: string, seat: string, dead = false) =>
      ({ id, name: id, seat_id: seat, status: "active", level: 1, hp: 1, hp_max: 1, dead }) as never;
    expect(myHero({ a: h("a", "s1", true), b: h("b", "s1") }, "s1")?.id).toBe("b");
    expect(myHero({ a: h("a", "s2") }, "s1")).toBeNull();
    useGame.getState().reset();
    useGame.getState().apply(env("state.actions", { actions: ["chat.ooc"], blocked: { "chat.play": "Идёт бой, сейчас ход: Гоблин." } }));
    expect(sendQuick("Атакую", [{ verb: "attack" }])).toBe("Идёт бой, сейчас ход: Гоблин.");
  });
});
