// Видимое этому участнику состояние кампании. Меняется только событиями сервера (документ дизайна: клиент
// ничего не считает и не угадывает).
import { create } from "zustand";
import type { Connection } from "../lib/socket";
import type { ChatMessage, Envelope, SeatState, Snapshot } from "../lib/types";

export const HISTORY_CAP = 500;

interface GameState {
  connection: Connection;
  connectionDetail: string | null;
  snapshot: Omit<Snapshot, "messages"> | null;
  seats: SeatState[];
  messages: ChatMessage[];
  masterStage: string | null;
  setConnection(c: Connection, detail?: string): void;
  apply(e: Envelope): void;
  reset(): void;
}

/** Сообщения по порядку seq, без повторов: досылка после переподключения может прислать уже виденное. */
export function mergeMessages(have: ChatMessage[], add: ChatMessage[]): ChatMessage[] {
  if (!add.length) return have;
  const bySeq = new Map(have.map((m) => [m.seq, m]));
  for (const m of add) bySeq.set(m.seq, m);
  const out = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  return out.length > HISTORY_CAP ? out.slice(out.length - HISTORY_CAP) : out;
}

const initial = {
  connection: "connecting" as Connection,
  connectionDetail: null,
  snapshot: null,
  seats: [],
  messages: [],
  masterStage: null,
};

export const useGame = create<GameState>((set) => ({
  ...initial,

  setConnection(connection, detail) {
    set({ connection, connectionDetail: detail ?? null });
  },

  apply(e) {
    switch (e.type) {
      case "state.snapshot": {
        const { messages, ...rest } = e.payload as unknown as Snapshot;
        set((s) => ({
          snapshot: rest,
          seats: rest.seats,
          messages: rest.replay ? mergeMessages(s.messages, messages) : mergeMessages([], messages),
        }));
        return;
      }
      case "message.new":
        set((s) => ({ messages: mergeMessages(s.messages, [e.payload as unknown as ChatMessage]) }));
        return;
      case "presence.changed": {
        const p = e.payload as { seat_id: string | null; status: "online" | "offline" };
        set((s) => ({ seats: s.seats.map((x) => (x.id === p.seat_id ? { ...x, presence: p.status } : x)) }));
        return;
      }
      case "master.status": {
        const stage = (e.payload as { stage: string }).stage;
        set({ masterStage: stage === "idle" ? null : stage });
        return;
      }
    }
  },

  reset() {
    set(initial);
  },
}));
