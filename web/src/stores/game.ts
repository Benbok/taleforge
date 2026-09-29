// Видимое этому участнику состояние кампании. Меняется только событиями сервера (документ дизайна: клиент
// ничего не считает и не угадывает). Своя реплика видна сразу с пометкой «отправляется», пока сервер её не примет.
import { create } from "zustand";
import type { Connection, GameSocket } from "../lib/socket";
import type {
  ChatMessage,
  EntityCard,
  EntityType,
  Envelope,
  Explained,
  HeroSheet,
  HeroPublic,
  PendingReply,
  ReactionPrompt,
  Scene,
  SeatState,
  SessionSummary,
  Snapshot,
  Turn,
  Vote,
} from "../lib/types";

export const HISTORY_CAP = 500;

export interface Pending {
  clientId: string;
  text: string;
  whisper: boolean;
  at: number;
  voice?: boolean; // голосовая: текст появится, когда сервер её расшифрует
}

/** Плашка в ленте, которую видит только этот игрок: «Вы узнали больше о…». */
export interface LocalNote {
  id: string;
  afterSeq: number;
  text: string;
  entityId?: string;
}

interface GameState {
  socket: GameSocket | null;
  connection: Connection;
  connectionDetail: string | null;
  snapshot: Omit<
    Snapshot,
    "messages" | "seats" | "heroes" | "scene" | "actions" | "blocked" | "turn" | "pending" | "reaction" | "summary" | "votes"
  > | null;
  seats: SeatState[];
  heroes: Record<string, HeroPublic>;
  scene: Scene | null;
  turn: Turn | null;
  actions: string[];
  blocked: Record<string, string>;
  myPending: PendingReply | null;
  restored: string | null;
  messages: ChatMessage[];
  pending: Pending[];
  rejected: { text: string; reason: string } | null;
  notice: string | null;
  notes: LocalNote[];
  masterStage: string | null;
  cards: Record<string, EntityCard>;
  types: Record<string, EntityType>;
  /** Полный лист своего героя и его разборы «почему такое число» по ключу величины. */
  sheet: HeroSheet | null;
  explained: Record<string, Explained>;
  /** Открытая кнопка реакции этого игрока и итог последней сессии (показывается на паузе). */
  reaction: ReactionPrompt | null;
  summary: SessionSummary | null;
  /** Открытые голосования: кто-то ушёл из сети во время сессии (раздел 11). */
  votes: Vote[];
  /** За какое место сейчас пишет этот игрок: null — за своего героя, иначе — за героя ушедшего по голосованию. */
  playAs: string | null;
  /** Что можно сейчас герою ушедшего, которого ведёт этот игрок, по месту. */
  standIn: Record<string, { actions: string[]; blocked: Record<string, string>; pending: PendingReply | null }>;
  setPlayAs(seat: string | null): void;
  setSheet(s: HeroSheet | null): void;
  setSocket(s: GameSocket | null): void;
  setConnection(c: Connection, detail?: string): void;
  addPending(p: Pending): void;
  clearRejected(): void;
  clearRestored(): void;
  setTypes(t: Record<string, EntityType>): void;
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
  socket: null,
  connection: "connecting" as Connection,
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
  reaction: null,
  summary: null,
  votes: [],
  playAs: null,
  standIn: {},
};

/** Места, чьих героев этот игрок ведёт за ушедших. */
export function standInFor(s: Pick<GameState, "snapshot">): string[] {
  return s.snapshot?.me?.stand_in_for ?? [];
}

export const useGame = create<GameState>((set, get) => ({
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

  setPlayAs(playAs) {
    set({ playAs });
  },

  setSheet(sheet) {
    set({ sheet, explained: {} });
  },

  setTypes(t) {
    set((s) => ({ types: { ...s.types, ...t } }));
  },

  apply(e) {
    const p = e.payload as Record<string, unknown>;
    switch (e.type) {
      case "state.snapshot": {
        const { messages, seats, heroes, scene, actions, blocked, turn, pending, reaction, summary, votes, ...rest } =
          p as unknown as Snapshot;
        set((s) => ({
          votes: votes ?? [],
          playAs: s.playAs && rest.me?.stand_in_for?.includes(s.playAs) ? s.playAs : null,
          standIn: {},
          reaction: reaction ?? null,
          summary: summary ?? null,
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
        const m = p as unknown as ChatMessage;
        const mine = get().snapshot?.me?.seat_id;
        const also = standInFor(get());
        set((s) => {
          // своя реплика пришла от сервера — снимаем самую раннюю пометку «отправляется»
          const own = (mine && m.seat_id === mine) || (!!m.seat_id && also.includes(m.seat_id));
          const pending =
            own && ["action", "speech", "whisper", "ooc", "narration"].includes(m.kind)
              ? s.pending.slice(1)
              : s.pending;
          return { messages: mergeMessages(s.messages, [m]), pending };
        });
        return;
      }
      case "message.rejected": {
        const clientId = p.client_id as string | undefined;
        set((s) => {
          const gone = s.pending.find((x) => x.clientId === clientId) ?? s.pending[0];
          return {
            pending: s.pending.filter((x) => x !== gone),
            // у голосовой сервер возвращает расшифровку: её можно поправить и отправить текстом
            rejected: {
              text: typeof p.text === "string" ? p.text : (gone?.text ?? ""),
              reason: String(p.reason ?? "реплика не принята"),
            },
          };
        });
        return;
      }
      case "message.notice":
        set({ notice: String(p.text ?? "") });
        return;
      case "presence.changed": {
        const x = p as { seat_id: string | null; status: SeatState["presence"] };
        set((s) => ({ seats: s.seats.map((seat) => (seat.id === x.seat_id ? { ...seat, presence: x.status } : seat)) }));
        return;
      }
      case "vote.started":
      case "vote.updated": {
        const v = p as unknown as Vote;
        set((s) => ({ votes: [...s.votes.filter((x) => x.vote_id !== v.vote_id), v] }));
        return;
      }
      case "vote.ended":
        set((s) => ({ votes: s.votes.filter((x) => x.vote_id !== p.vote_id) }));
        return;
      case "stand_in.changed": {
        const x = p as { seat_id: string; stand_in: SeatState["stand_in"] };
        set((s) => {
          if (!s.snapshot) return {};
          const me = s.snapshot.me;
          const was = me.stand_in_for ?? [];
          const mine = !!x.stand_in && x.stand_in.user_id === me.user_id;
          const standing = mine ? [...new Set([...was, x.seat_id])] : was.filter((id) => id !== x.seat_id);
          return {
            seats: s.seats.map((seat) => (seat.id === x.seat_id ? { ...seat, stand_in: x.stand_in ?? null } : seat)),
            snapshot: { ...s.snapshot, me: { ...me, stand_in_for: standing } },
            playAs: standing.includes(s.playAs ?? "") ? s.playAs : null,
          };
        });
        return;
      }
      case "master.status": {
        const stage = String(p.stage);
        set({ masterStage: stage === "idle" ? null : stage });
        return;
      }
      case "turn.changed":
        set((s) => ({ turn: (p.turn as Turn) ?? null, scene: s.scene ? { ...s.scene, turn: (p.turn as Turn) ?? null } : s.scene }));
        return;
      case "scene.updated":
        set({ scene: p as unknown as Scene, turn: ((p as unknown as Scene).turn as Turn) ?? null });
        return;
      case "reaction.prompt":
        set({ reaction: p as unknown as ReactionPrompt });
        return;
      case "error":
        if (p.code === "reaction_closed") set({ reaction: null });
        return;
      case "reaction.closed":
        set((s) => (s.reaction?.prompt_id === p.prompt_id ? { reaction: null } : {}));
        return;
      case "session.summary":
        set({ summary: p as unknown as SessionSummary });
        return;
      case "state.actions":
        if (p.as_seat) {
          const seat = String(p.as_seat);
          set((s) => ({
            standIn: {
              ...s.standIn,
              [seat]: {
                actions: (p.actions as string[]) ?? [],
                blocked: (p.blocked as Record<string, string>) ?? {},
                pending: (p.pending as PendingReply | null) ?? null,
              },
            },
          }));
          return;
        }
        set({
          actions: (p.actions as string[]) ?? [],
          blocked: (p.blocked as Record<string, string>) ?? {},
          myPending: (p.pending as PendingReply | null) ?? null,
        });
        return;
      case "message.state": {
        const ids = new Set((p.ids as string[]) ?? []);
        const state = p.state as ChatMessage["state"];
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
        const h = p.character as HeroSheet;
        // лист пришёл после изменения: прежние разборы чисел могли устареть
        if (h?.id)
          set((s) => ({
            sheet: { ...(s.sheet?.id === h.id ? s.sheet : {}), ...h } as HeroSheet, // имена класса и происхождения — из REST
            explained: {},
            heroes: { ...s.heroes, [h.id]: { ...s.heroes[h.id], ...h } },
          }));
        return;
      }
      case "stat.explained": {
        const x = p as unknown as Explained;
        set((s) => ({ explained: { ...s.explained, [x.stat]: x } }));
        return;
      }
      case "character.updated": {
        const h = p.character as HeroPublic;
        if (h?.id) set((s) => ({ heroes: { ...s.heroes, [h.id]: h } }));
        return;
      }
      case "entity.card": {
        const c = p as unknown as EntityCard;
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
