import { beforeEach, describe, expect, it } from "vitest";
import { HISTORY_CAP, mergeMessages, useGame } from "./game";
const msg = (seq, content = `m${seq}`) => ({
    id: `m${seq}`,
    seq,
    kind: "narration",
    seat_id: null,
    author: null,
    content,
    whisper: false,
    created_at: null,
});
const env = (type, payload, seq = null) => ({
    type,
    campaign_id: "c1",
    seq,
    payload: payload,
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
        const a = { ...msg(1), kind: "action", seat_id: "s1", state: "pending" };
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
