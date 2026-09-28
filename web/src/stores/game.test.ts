import { beforeEach, describe, expect, it } from "vitest";
import type { ChatMessage, Envelope } from "../lib/types";
import { HISTORY_CAP, mergeMessages, useGame } from "./game";

const msg = (seq: number, content = `m${seq}`): ChatMessage => ({
  id: `m${seq}`,
  seq,
  kind: "narration",
  seat_id: null,
  author: null,
  content,
  whisper: false,
  created_at: null,
});

const env = (type: string, payload: object, seq: number | null = null): Envelope => ({
  type,
  campaign_id: "c1",
  seq,
  payload: payload as Record<string, unknown>,
});

describe("хранилище игры", () => {
  beforeEach(() => useGame.getState().reset());

  it("сливает сообщения по seq без повторов и держит порядок", () => {
    const out = mergeMessages([msg(1), msg(3)], [msg(2), msg(3, "новое")]);
    expect(out.map((m) => m.seq)).toEqual([1, 2, 3]);
    expect(out[2].content).toBe("новое");
    const many = mergeMessages([], Array.from({ length: HISTORY_CAP + 5 }, (_, i) => msg(i)));
    expect(many).toHaveLength(HISTORY_CAP);
    expect(many[0].seq).toBe(5);
  });

  it("применяет снимок, досылку, присутствие и статус мастера", () => {
    const g = useGame.getState;
    const seats = [{ id: "s1", role: "player", position: 1, occupant_type: "human", user_name: "Лина", presence: "offline" }];
    g().apply(env("state.snapshot", { messages: [msg(1)], seats, replay: false, campaign: { name: "К" } }, 1));
    expect(g().messages).toHaveLength(1);
    g().apply(env("message.new", msg(2), 2));
    g().apply(env("state.snapshot", { messages: [msg(2), msg(3)], seats, replay: true }, 3));
    expect(g().messages.map((m) => m.seq)).toEqual([1, 2, 3]);
    g().apply(env("state.snapshot", { messages: [msg(9)], seats, replay: false }, 9));
    expect(g().messages.map((m) => m.seq)).toEqual([9]); // новый вход — история заново

    g().apply(env("presence.changed", { seat_id: "s1", status: "online" }));
    expect(g().seats[0].presence).toBe("online");
    g().apply(env("master.status", { stage: "rolling" }));
    expect(g().masterStage).toBe("rolling");
    g().apply(env("master.status", { stage: "idle" }));
    expect(g().masterStage).toBeNull();
    g().apply(env("что-то.новое", {})); // неизвестные события игнорируются
  });
});
