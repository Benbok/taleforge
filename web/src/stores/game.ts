// Видимое этому участнику состояние кампании. Меняется только событиями сервера (документ дизайна: клиент
// ничего не считает и не угадывает). Своя реплика видна сразу с пометкой «отправляется», пока сервер её не примет.
import { create } from "zustand";
import type { Connection, GameSocket } from "../lib/socket";
import type {
  AudioState,
  ChatMessage,
  EntityCard,
  EntityType,
  Envelope,
  EventOf,
  Explained,
  HeroSheet,
  HeroPublic,
  PendingReply,
  ReactionPrompt,
  RestVote,
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
    | "messages"
    | "seats"
    | "heroes"
    | "scene"
    | "actions"
    | "blocked"
    | "turn"
    | "pending"
    | "reaction"
    | "summary"
    | "votes"
    | "rest_votes"
    | "audio"
  > | null;
  audio: AudioState | null; // звук сцены: что звучит в каждом слое
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
  /** Голосования группы за отдых, которые видит этот участник. */
  restVotes: RestVote[];
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

/** ``data`` сообщения сервер не описывает: её форма зависит от инструмента, разбирает её клиент (ChatMessage). */
const asMessages = (ms: EventOf<"message.new">["payload"][]): ChatMessage[] => ms as ChatMessage[];

const initial = {
  socket: null,
  connection: "connecting" as Connection,
  connectionDetail: null,
  snapshot: null,
  seats: [],
  heroes: {},
  scene: null,
  audio: null,
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
  restVotes: [],
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
    // e.payload сужается по e.type: формы событий приходят из контракта сервера (lib/api.gen.ts)
    switch (e.type) {
      case "state.snapshot": {
        const { messages, seats, heroes, scene, audio, actions, blocked, turn, pending, reaction, summary, votes, rest_votes, ...rest } =
          e.payload;
        set((s) => ({
          votes: votes ?? [],
          restVotes: rest_votes ?? [],
          playAs: s.playAs && rest.me?.stand_in_for?.includes(s.playAs) ? s.playAs : null,
          standIn: {},
          reaction: reaction ?? null,
          summary: summary ?? null,
          snapshot: rest,
          seats,
          heroes: Object.fromEntries((heroes ?? []).map((h) => [h.id, h])),
          scene: scene ?? null,
          audio: audio ?? null,
          turn: turn ?? null,
          actions: actions ?? [],
          blocked: blocked ?? {},
          myPending: pending ?? null,
          messages: rest.replay ? mergeMessages(s.messages, asMessages(messages)) : mergeMessages([], asMessages(messages)),
        }));
        return;
      }
      case "message.new": {
        const m: ChatMessage = { ...asMessages([e.payload])[0], fresh: true };
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
      case "message.chunk": {
        // черновик мастера по кускам: сообщение появляется до message.new, финальный текст его заменит
        const p = e.payload;
        set((s) => {
          if (!s.messages.some((m) => m.id === p.id)) {
            const draft: ChatMessage = {
              id: p.id,
              seq: p.seq,
              kind: p.kind,
              seat_id: p.seat_id,
              author: null,
              content: p.chunk,
              whisper: false,
              created_at: null,
              fresh: true,
            };
            return { messages: mergeMessages(s.messages, [draft]) };
          }
          return {
            messages: s.messages.map((m) => (m.id === p.id ? { ...m, content: p.reset ? p.chunk : m.content + p.chunk } : m)),
          };
        });
        return;
      }
      case "message.rejected": {
        const p = e.payload;
        set((s) => {
          const gone = s.pending.find((x) => x.clientId === p.client_id) ?? s.pending[0];
          return {
            pending: s.pending.filter((x) => x !== gone),
            // у голосовой сервер возвращает расшифровку: её можно поправить и отправить текстом
            rejected: { text: p.text ?? gone?.text ?? "", reason: p.reason || "реплика не принята" },
          };
        });
        return;
      }
      case "message.notice":
        set({ notice: e.payload.text });
        return;
      case "presence.changed": {
        const x = e.payload;
        set((s) => ({ seats: s.seats.map((seat) => (seat.id === x.seat_id ? { ...seat, presence: x.status } : seat)) }));
        return;
      }
      case "vote.started":
      case "vote.updated": {
        const v: Vote = e.payload;
        set((s) => ({ votes: [...s.votes.filter((x) => x.vote_id !== v.vote_id), v] }));
        return;
      }
      case "vote.ended": {
        const id = e.payload.vote_id;
        set((s) => ({ votes: s.votes.filter((x) => x.vote_id !== id) }));
        return;
      }
      case "rest.vote": {
        const v: RestVote = e.payload;
        set((s) => ({ restVotes: [...s.restVotes.filter((x) => x.vote_id !== v.vote_id), v] }));
        return;
      }
      case "rest.ended": {
        const id = e.payload.vote_id;
        set((s) => ({ restVotes: s.restVotes.filter((x) => x.vote_id !== id) }));
        return;
      }
      case "stand_in.changed": {
        const x = e.payload;
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
        const stage = e.payload.stage;
        set({ masterStage: stage === "idle" ? null : stage });
        return;
      }
      case "turn.changed": {
        const turn: Turn | null = e.payload.turn ?? null;
        set((s) => ({ turn, scene: s.scene ? { ...s.scene, turn } : s.scene }));
        return;
      }
      case "audio.state": {
        const { cues: _cues, ...state } = e.payload;
        set({ audio: state });
        return;
      }
      case "scene.updated": {
        const scene: Scene = e.payload;
        set({ scene, turn: scene.turn ?? null });
        return;
      }
      case "reaction.prompt":
        set({ reaction: e.payload });
        return;
      case "error":
        if (e.payload.code === "reaction_closed") set({ reaction: null });
        return;
      case "reaction.closed": {
        const id = e.payload.prompt_id;
        set((s) => (s.reaction?.prompt_id === id ? { reaction: null } : {}));
        return;
      }
      case "session.summary":
        set({ summary: e.payload });
        return;
      case "state.actions": {
        const { as_seat, actions, blocked, pending } = e.payload;
        if (as_seat) {
          set((s) => ({ standIn: { ...s.standIn, [as_seat]: { actions, blocked, pending } } }));
          return;
        }
        set({ actions, blocked, myPending: pending });
        return;
      }
      case "message.state": {
        const ids = new Set(e.payload.ids);
        const state = e.payload.state;
        set((s) => ({ messages: s.messages.map((m) => (ids.has(m.id) ? { ...m, state } : m)) }));
        return;
      }
      case "message.withdrawn": {
        const { id, text } = e.payload;
        set((s) => ({
          messages: s.messages.filter((m) => m.id !== id),
          myPending: s.myPending?.id === id ? null : s.myPending,
          restored: typeof text === "string" ? text : s.restored,
        }));
        return;
      }
      case "character.sheet": {
        // лист на сервере пока описан не весь (app/gateway/protocol.py, HeroSheet): остальное — по типам клиента
        const h = e.payload.character as unknown as HeroSheet;
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
        const x = e.payload as Explained;
        set((s) => ({ explained: { ...s.explained, [x.stat]: x } }));
        return;
      }
      case "character.updated": {
        const h: HeroPublic = e.payload.character;
        if (h?.id) set((s) => ({ heroes: { ...s.heroes, [h.id]: h } }));
        return;
      }
      case "entity.card": {
        const c = e.payload as EntityCard;
        set((s) => ({
          cards: { ...s.cards, [c.id]: c },
          types: c.type ? { ...s.types, [c.id]: c.type } : s.types,
        }));
        return;
      }
      case "knowledge.revealed": {
        const p = e.payload;
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
