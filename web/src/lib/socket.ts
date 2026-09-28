// Соединение с игрой (ТЗ, раздел 12): auth → campaign.join с последним seq → state.snapshot и досылка.
// При обрыве — повторы с растущей паузой 1, 2, 4, 8 секунд, дальше каждые 10. Класс не знает про React:
// события отдаёт подписчику, а фабрика сокета и таймеры подменяются в тестах.
import type { Envelope } from "./types";

export type Connection = "connecting" | "open" | "reconnecting" | "closed";

export const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const PING_MS = 25000;
// после этих событий состояние проще запросить заново: сменились места или сессия
const REJOIN = new Set(["seat.changed", "session.started", "session.paused", "session.ended"]);

export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
}

export interface SocketOptions {
  url: string;
  token: () => string | null;
  campaignId: string;
  onEvent: (e: Envelope) => void;
  onStatus: (s: Connection, detail?: string) => void;
  factory?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (id: unknown) => void;
}

export function socketUrl(loc: Location = window.location): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws`;
}

export class GameSocket {
  lastSeq: number | null = null;
  private ws: SocketLike | null = null;
  private attempt = 0;
  private stopped = false;
  private retry: unknown = null;
  private ping: unknown = null;
  private readonly o: Required<SocketOptions>;

  constructor(opts: SocketOptions) {
    this.o = {
      factory: (url) => new WebSocket(url) as unknown as SocketLike,
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (id) => clearTimeout(id as number),
      ...opts,
    };
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.o.clearTimer(this.retry);
    this.o.clearTimer(this.ping);
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    this.o.onStatus("closed");
  }

  /** Отправляет событие игры. false — соединения сейчас нет, и отправлять нечего: текст остаётся у игрока. */
  send(type: string, payload: Record<string, unknown> = {}): boolean {
    if (!this.ws || this.ws.readyState !== 1 || !this.joined) return false;
    this.ws.send(JSON.stringify({ type, payload }));
    return true;
  }

  private joined = false;

  private open(): void {
    this.joined = false;
    this.o.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const ws = this.o.factory(this.o.url);
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", payload: { token: this.o.token() } }));
    ws.onmessage = (ev) => this.handle(ws, ev.data);
    ws.onclose = () => {
      if (this.ws !== ws) return; // закрыли сами
      this.ws = null;
      this.joined = false;
      this.o.clearTimer(this.ping);
      if (this.stopped) return;
      const delay = RETRY_DELAYS_MS[Math.min(this.attempt, RETRY_DELAYS_MS.length - 1)];
      this.attempt += 1;
      this.o.onStatus("reconnecting");
      this.retry = this.o.setTimer(() => !this.stopped && this.open(), delay);
    };
  }

  private join(ws: SocketLike): void {
    ws.send(JSON.stringify({ type: "campaign.join", payload: { campaign_id: this.o.campaignId, last_seq: this.lastSeq } }));
  }

  private handle(ws: SocketLike, raw: string): void {
    let e: Envelope;
    try {
      e = JSON.parse(raw);
    } catch {
      return;
    }
    if (!e || typeof e.type !== "string") return;
    if (e.type === "auth.ok") return this.join(ws);
    if (e.type === "error" && (e.payload as { code?: string }).code === "unauthorized") {
      this.stopped = true;
      this.o.onStatus("closed", "unauthorized");
      ws.close();
      return;
    }
    if (e.type === "state.snapshot") {
      this.attempt = 0;
      this.joined = true;
      this.o.onStatus("open");
      this.o.clearTimer(this.ping);
      const beat = () => {
        this.ping = this.o.setTimer(() => {
          if (this.ws === ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "ping", payload: {} }));
          beat();
        }, PING_MS);
      };
      beat();
    }
    if (typeof e.seq === "number" && e.type !== "state.snapshot") this.lastSeq = Math.max(this.lastSeq ?? 0, e.seq);
    if (e.type === "state.snapshot") {
      const msgs = (e.payload as { messages?: { seq: number }[] }).messages ?? [];
      const top = Math.max(e.seq ?? 0, ...msgs.map((m) => m.seq));
      this.lastSeq = Math.max(this.lastSeq ?? 0, top);
    }
    this.o.onEvent(e);
    if (REJOIN.has(e.type) && this.joined) this.join(ws);
  }
}
