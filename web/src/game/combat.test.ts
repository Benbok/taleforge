import { beforeEach, describe, expect, it } from "vitest";
import type { Envelope, SceneEntity } from "../lib/types";
import { useGame } from "../stores/game";
import { byZone, myTurn, ringState } from "./combat";

const env = (type: string, payload: object): Envelope => ({
  type,
  campaign_id: "c1",
  seq: null,
  payload: payload as Record<string, unknown>,
});

const ent = (id: string, zone: string, kind = "creature"): SceneEntity => ({ id, name: id, kind, zone, attitude: "hostile" });

describe("экран боя", () => {
  beforeEach(() => useGame.getState().reset());

  it("кольцо хода: спокойное, за 60 с жёлтое, за 15 с красное", () => {
    expect(ringState(200, 300)).toEqual({ pct: 200 / 300, tone: "calm" });
    expect(ringState(60, 300).tone).toBe("warn");
    expect(ringState(15, 300).tone).toBe("urgent");
    expect(ringState(-3, 300).pct).toBe(0);
  });

  it("существа раскладываются по зонам, предметы — нет", () => {
    const z = byZone([ent("a", "вплотную"), ent("b", "далеко"), ent("c", "где-то"), ent("d", "близко", "item")]);
    expect(z["вплотную"].map((e) => e.id)).toEqual(["a"]);
    expect(z["далеко"].map((e) => e.id)).toEqual(["b", "c"]);
    expect(z["близко"]).toEqual([]);
  });

  it("мой ход — только когда ход у моего места", () => {
    const t = { round: 1, actor_id: "h", name: "Иван", seat_id: "s1", deadline: null, submitted: false };
    expect(myTurn(t, "s1")).toBe(true);
    expect(myTurn(t, "s2")).toBe(false);
    expect(myTurn(null, "s1")).toBe(false);
  });

  it("кнопка реакции открывается и закрывается по своему id, в том числе ошибкой «время вышло»", () => {
    const prompt = { prompt_id: "rx1", character_id: "h", trigger: "волк убегает", options: [], expires_at: 1 };
    const { apply } = useGame.getState();
    apply(env("reaction.prompt", prompt));
    expect(useGame.getState().reaction?.prompt_id).toBe("rx1");
    apply(env("reaction.closed", { prompt_id: "другой" }));
    expect(useGame.getState().reaction).not.toBeNull();
    apply(env("reaction.closed", { prompt_id: "rx1" }));
    expect(useGame.getState().reaction).toBeNull();
    apply(env("reaction.prompt", prompt));
    apply(env("error", { code: "reaction_closed", message: "время реакции вышло" }));
    expect(useGame.getState().reaction).toBeNull();
  });

  it("итог сессии приходит событием и в снимке", () => {
    const { apply } = useGame.getState();
    apply(env("session.summary", { recap: "Отряд дошёл до моста.", events: ["бой у моста"], quests: [] }));
    expect(useGame.getState().summary?.recap).toBe("Отряд дошёл до моста.");
  });
});
