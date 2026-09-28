// Видимое этому участнику состояние кампании. Меняется только событиями сервера (документ дизайна: клиент
// ничего не считает и не угадывает). Своя реплика видна сразу с пометкой «отправляется», пока сервер её не примет.
import { create } from "zustand";
export const HISTORY_CAP = 500;
/** Сообщения по порядку seq, без повторов: досылка после переподключения может прислать уже виденное. */
export function mergeMessages(have, add) {
    if (!add.length)
        return have;
    const bySeq = new Map(have.map((m) => [m.seq, m]));
    for (const m of add)
        bySeq.set(m.seq, m);
    const out = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
    return out.length > HISTORY_CAP ? out.slice(out.length - HISTORY_CAP) : out;
}
const initial = {
    socket: null,
    connection: "connecting",
    connectionDetail: null,
    snapshot: null,
    seats: [],
    heroes: {},
    scene: null,
    turn: null,
    actions: [],
    blocked: {},
    myPending: null,
    restored: null,
    messages: [],
    pending: [],
    rejected: null,
    notice: null,
    notes: [],
    masterStage: null,
    cards: {},
    types: {},
    sheet: null,
    explained: {},
};
export const useGame = create((set, get) => ({
    ...initial,
    setSocket(socket) {
        set({ socket });
    },
    setConnection(connection, detail) {
        set({ connection, connectionDetail: detail ?? null });
    },
    addPending(p) {
        set((s) => ({ pending: [...s.pending, p], rejected: null, notice: null }));
    },
    clearRejected() {
        set({ rejected: null });
    },
    clearRestored() {
        set({ restored: null });
    },
    setSheet(sheet) {
        set({ sheet, explained: {} });
    },
    setTypes(t) {
        set((s) => ({ types: { ...s.types, ...t } }));
    },
    apply(e) {
        const p = e.payload;
        switch (e.type) {
            case "state.snapshot": {
                const { messages, seats, heroes, scene, actions, blocked, turn, pending, ...rest } = p;
                set((s) => ({
                    snapshot: rest,
                    seats,
                    heroes: Object.fromEntries((heroes ?? []).map((h) => [h.id, h])),
                    scene: scene ?? null,
                    turn: turn ?? null,
                    actions: actions ?? [],
                    blocked: blocked ?? {},
                    myPending: pending ?? null,
                    messages: rest.replay ? mergeMessages(s.messages, messages) : mergeMessages([], messages),
                }));
                return;
            }
            case "message.new": {
                const m = p;
                const mine = get().snapshot?.me?.seat_id;
                set((s) => {
                    // своя реплика пришла от сервера — снимаем самую раннюю пометку «отправляется»
                    const pending = mine && m.seat_id === mine && ["action", "speech", "whisper", "ooc", "narration"].includes(m.kind)
                        ? s.pending.slice(1)
                        : s.pending;
                    return { messages: mergeMessages(s.messages, [m]), pending };
                });
                return;
            }
            case "message.rejected": {
                const clientId = p.client_id;
                set((s) => {
                    const gone = s.pending.find((x) => x.clientId === clientId) ?? s.pending[0];
                    return {
                        pending: s.pending.filter((x) => x !== gone),
                        rejected: { text: gone?.text ?? "", reason: String(p.reason ?? "реплика не принята") },
                    };
                });
                return;
            }
            case "message.notice":
                set({ notice: String(p.text ?? "") });
                return;
            case "presence.changed": {
                const x = p;
                set((s) => ({ seats: s.seats.map((seat) => (seat.id === x.seat_id ? { ...seat, presence: x.status } : seat)) }));
                return;
            }
            case "master.status": {
                const stage = String(p.stage);
                set({ masterStage: stage === "idle" ? null : stage });
                return;
            }
            case "turn.changed":
                set((s) => ({ turn: p.turn ?? null, scene: s.scene ? { ...s.scene, turn: p.turn ?? null } : s.scene }));
                return;
            case "scene.updated":
                set({ scene: p, turn: p.turn ?? null });
                return;
            case "state.actions":
                set({
                    actions: p.actions ?? [],
                    blocked: p.blocked ?? {},
                    myPending: p.pending ?? null,
                });
                return;
            case "message.state": {
                const ids = new Set(p.ids ?? []);
                const state = p.state;
                set((s) => ({ messages: s.messages.map((m) => (ids.has(m.id) ? { ...m, state } : m)) }));
                return;
            }
            case "message.withdrawn": {
                const id = String(p.id);
                set((s) => ({
                    messages: s.messages.filter((m) => m.id !== id),
                    myPending: s.myPending?.id === id ? null : s.myPending,
                    restored: typeof p.text === "string" ? p.text : s.restored,
                }));
                return;
            }
            case "character.sheet": {
                const h = p.character;
                // лист пришёл после изменения: прежние разборы чисел могли устареть
                if (h?.id)
                    set((s) => ({
                        sheet: { ...(s.sheet?.id === h.id ? s.sheet : {}), ...h }, // имена класса и происхождения — из REST
                        explained: {},
                        heroes: { ...s.heroes, [h.id]: { ...s.heroes[h.id], ...h } },
                    }));
                return;
            }
            case "stat.explained": {
                const x = p;
                set((s) => ({ explained: { ...s.explained, [x.stat]: x } }));
                return;
            }
            case "character.updated": {
                const h = p.character;
                if (h?.id)
                    set((s) => ({ heroes: { ...s.heroes, [h.id]: h } }));
                return;
            }
            case "entity.card": {
                const c = p;
                set((s) => ({
                    cards: { ...s.cards, [c.id]: c },
                    types: c.type ? { ...s.types, [c.id]: c.type } : s.types,
                }));
                return;
            }
            case "knowledge.revealed": {
                const id = String(p.entity_id);
                const last = get().messages.at(-1)?.seq ?? 0;
                set((s) => {
                    const { [id]: _stale, ...cards } = s.cards; // карточку надо запросить заново: знаний стало больше
                    void _stale;
                    return {
                        cards,
                        notes: [...s.notes, { id: `k${Date.now()}`, afterSeq: last, text: `Вы узнали больше о: ${p.name ?? "…"}`, entityId: id }],
                    };
                });
                return;
            }
        }
    },
    reset() {
        set(initial);
    },
}));
