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

  it("голосование, замена ушедшего и игра за его героя", () => {
    const g = useGame.getState;
    const me = { user_id: "u2", seat_id: "s2", role: "player", is_owner: false, stand_in_for: [] };
    const seats = [
      { id: "s1", role: "player", position: 1, occupant_type: "human", user_name: "Арагорн", presence: "online" },
      { id: "s2", role: "player", position: 2, occupant_type: "human", user_name: "Гимли", presence: "online" },
    ];
    g().apply(env("state.snapshot", { messages: [], seats, replay: false, me, actions: [], blocked: {}, votes: [] }, 0));
    g().apply(env("presence.changed", { seat_id: "s1", status: "reconnecting" }));
    expect(g().seats[0].presence).toBe("reconnecting");

    const vote = { vote_id: "v1", seat_id: "s1", subject: "player", who: "Арагорн", hero: "Бран", voters: ["s2"], voted: [] };
    g().apply(env("vote.started", { ...vote, tally: { "seat:s2": 0, pause: 0 } }));
    g().apply(env("vote.updated", { ...vote, voted: ["s2"], tally: { "seat:s2": 1, pause: 0 } }));
    expect(g().votes).toHaveLength(1);
    expect(g().votes[0].voted).toEqual(["s2"]);
    g().apply(env("vote.ended", { ...vote, outcome: "seat:s2" }));
    expect(g().votes).toEqual([]);

    g().apply(env("stand_in.changed", { seat_id: "s1", stand_in: { user_id: "u2", name: "Гимли" } }));
    expect(g().snapshot?.me.stand_in_for).toEqual(["s1"]);
    expect(g().seats[0].stand_in?.name).toBe("Гимли");
    g().setPlayAs("s1");
    g().apply(env("state.actions", { as_seat: "s1", actions: ["chat.play"], blocked: {}, pending: null }));
    expect(g().standIn.s1.actions).toEqual(["chat.play"]);
    expect(g().actions).toEqual([]); // свои действия не тронуты

    // реплика за героя ушедшего снимает пометку «отправляется»
    g().addPending({ clientId: "a", text: "Бран идёт", whisper: false, at: 1 });
    g().apply(env("message.new", { ...msg(5), kind: "action", seat_id: "s1" }, 5));
    expect(g().pending).toEqual([]);

    g().apply(env("stand_in.changed", { seat_id: "s1", stand_in: null }));
    expect(g().snapshot?.me.stand_in_for).toEqual([]);
    expect(g().playAs).toBeNull();
  });

  it("снимает «отправляется» своей реплики, а отказ возвращает текст с причиной", () => {
    const g = useGame.getState;
    const me = { user_id: "u1", seat_id: "s1", role: "player", is_owner: false };
    g().apply(env("state.snapshot", { messages: [], seats: [], replay: false, me, actions: ["chat.play"], blocked: {} }, 0));
    g().addPending({ clientId: "a", text: "Открываю дверь", whisper: false, at: 1 });
    g().addPending({ clientId: "b", text: "Кричу", whisper: false, at: 2 });
    g().apply(env("message.new", { ...msg(1), kind: "action", seat_id: "s1" }, 1));
    expect(g().pending.map((p) => p.clientId)).toEqual(["b"]);
    g().apply(env("message.rejected", { client_id: "b", reason: "Идёт бой, сейчас ход: Гоблин." }));
    expect(g().pending).toEqual([]);
    expect(g().rejected).toEqual({ text: "Кричу", reason: "Идёт бой, сейчас ход: Гоблин." });
    g().clearRejected();
    expect(g().rejected).toBeNull();
  });

  it("кнопки и причины приходят от сервера", () => {
    const g = useGame.getState;
    g().apply(env("state.actions", { actions: ["session.pause", "chat.ooc"], blocked: { "chat.play": "пауза" } }));
    expect(g().actions).toEqual(["session.pause", "chat.ooc"]);
    expect(g().blocked["chat.play"]).toBe("пауза");
  });

  it("новое знание сбрасывает карточку и добавляет плашку", () => {
    const g = useGame.getState;
    g().apply(env("entity.card", { id: "en1", type: "creature", name: "Гоблин", level: 0 }));
    expect(g().types.en1).toBe("creature");
    g().apply(env("knowledge.revealed", { entity_id: "en1", name: "Гоблин", level: 1 }));
    expect(g().cards.en1).toBeUndefined();
    expect(g().notes[0].text).toContain("Гоблин");
  });

  it("статус реплики, отмена и возврат текста автору", () => {
    const g = useGame.getState;
    const me = { user_id: "u1", seat_id: "s1", role: "player", is_owner: false };
    const a = { ...msg(1), kind: "action", seat_id: "s1", state: "pending" as const };
    const pending = { id: "m1", created_at: "2026-09-28T10:00:00+00:00" };
    g().apply(env("state.snapshot", { messages: [a], seats: [], replay: false, me, actions: [], blocked: {}, pending, collect_window_sec: 60 }, 1));
    expect(g().myPending).toEqual(pending);
    g().apply(env("message.state", { ids: ["m1", "чужой"], state: "processing" }));
    expect(g().messages[0].state).toBe("processing");
    g().apply(env("state.actions", { actions: [], blocked: {}, pending: null }));
    expect(g().myPending).toBeNull();
    g().apply(env("message.withdrawn", { id: "m1", seq: 1 }));
    expect(g().messages).toEqual([]);
    expect(g().restored).toBeNull();
    g().apply(env("message.withdrawn", { id: "m1", seq: 1, text: "Лезу на стену" }));
    expect(g().restored).toBe("Лезу на стену");
    g().clearRestored();
    expect(g().restored).toBeNull();
  });
});
