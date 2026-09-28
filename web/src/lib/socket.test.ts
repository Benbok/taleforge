import { describe, expect, it } from "vitest";
import { GameSocket, RETRY_DELAYS_MS, type SocketLike } from "./socket";
import type { Envelope } from "./types";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: { type: string; payload: Record<string, unknown> }[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  recv(type: string, payload: Record<string, unknown> = {}, seq: number | null = null) {
    this.onmessage?.({ data: JSON.stringify({ type, campaign_id: "c1", seq, payload }) });
  }
  drop() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const events: Envelope[] = [];
  const statuses: string[] = [];
  const sock = new GameSocket({
    url: "ws://x/ws",
    token: () => "jwt",
    campaignId: "c1",
    onEvent: (e) => events.push(e),
    onStatus: (s) => statuses.push(s),
    factory: () => {
      const s = new FakeSocket();
      sockets.push(s);
      return s;
    },
    setTimer: (fn, ms) => timers.push({ fn, ms }) - 1,
    clearTimer: () => undefined,
  });
  return { sock, sockets, timers, events, statuses };
}

const snapshot = (seq: number, messages: { seq: number }[] = []) => ({ messages, seats: [], replay: false, seq });

describe("GameSocket", () => {
  it("входит, присоединяется и досылает пропущенное после обрыва", () => {
    const { sock, sockets, timers, events, statuses } = setup();
    sock.start();
    const a = sockets[0];
    a.open();
    expect(a.sent[0]).toEqual({ type: "auth", payload: { token: "jwt" } });
    a.recv("auth.ok");
    expect(a.sent[1]).toEqual({ type: "campaign.join", payload: { campaign_id: "c1", last_seq: null } });
    expect(sock.send("message.send", { text: "до входа" })).toBe(false);
    a.recv("state.snapshot", snapshot(7, [{ seq: 5 }]), 7);
    expect(statuses.at(-1)).toBe("open");
    a.recv("message.new", { seq: 9 }, 9);
    expect(sock.lastSeq).toBe(9);
    expect(sock.send("message.send", { text: "привет" })).toBe(true);
    expect(events.map((e) => e.type)).toEqual(["state.snapshot", "message.new"]);

    a.drop();
    expect(statuses.at(-1)).toBe("reconnecting");
    const retry = timers.find((t) => t.ms === RETRY_DELAYS_MS[0])!;
    expect(sock.send("message.send", {})).toBe(false);
    retry.fn();
    const b = sockets[1];
    b.open();
    b.recv("auth.ok");
    expect(b.sent[1].payload).toEqual({ campaign_id: "c1", last_seq: 9 });
  });

  it("растит паузу между повторами и сбрасывает её после входа", () => {
    const { sock, sockets, timers } = setup();
    sock.start();
    for (let i = 0; i < 7; i++) {
      sockets.at(-1)!.drop();
      timers.at(-1)!.fn();
    }
    expect(timers.map((t) => t.ms)).toEqual([1000, 2000, 4000, 8000, 10000, 10000, 10000]);
    const s = sockets.at(-1)!;
    s.open();
    s.recv("auth.ok");
    s.recv("state.snapshot", snapshot(0), 0);
    s.drop();
    expect(timers.at(-1)!.ms).toBe(1000);
  });

  it("перестаёт переподключаться без входа и после stop", () => {
    const { sock, sockets, timers, statuses } = setup();
    sock.start();
    sockets[0].open();
    sockets[0].recv("error", { code: "unauthorized" });
    expect(statuses.at(-1)).toBe("closed");
    expect(timers.filter((t) => t.ms < 25000)).toHaveLength(0);

    const other = setup();
    other.sock.start();
    other.sock.stop();
    expect(other.sockets[0].readyState).toBe(3);
    expect(other.timers).toHaveLength(0);
  });

  it("после смены мест или сессии запрашивает состояние заново", () => {
    const { sock, sockets } = setup();
    sock.start();
    const a = sockets[0];
    a.open();
    a.recv("auth.ok");
    a.recv("state.snapshot", snapshot(3), 3);
    a.recv("session.paused");
    expect(a.sent.at(-1)).toEqual({ type: "campaign.join", payload: { campaign_id: "c1", last_seq: 3 } });
  });
});
