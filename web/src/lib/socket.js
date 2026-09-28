export const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 10000];
const PING_MS = 25000;
// после этих событий состояние проще запросить заново: сменились места или сессия
const REJOIN = new Set(["seat.changed", "session.started", "session.paused", "session.ended"]);
export function socketUrl(loc = window.location) {
    return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws`;
}
export class GameSocket {
    lastSeq = null;
    ws = null;
    attempt = 0;
    stopped = false;
    retry = null;
    ping = null;
    o;
    constructor(opts) {
        this.o = {
            factory: (url) => new WebSocket(url),
            setTimer: (fn, ms) => setTimeout(fn, ms),
            clearTimer: (id) => clearTimeout(id),
            ...opts,
        };
    }
    start() {
        this.stopped = false;
        this.open();
    }
    stop() {
        this.stopped = true;
        this.o.clearTimer(this.retry);
        this.o.clearTimer(this.ping);
        const ws = this.ws;
        this.ws = null;
        ws?.close();
        this.o.onStatus("closed");
    }
    /** Отправляет событие игры. false — соединения сейчас нет, и отправлять нечего: текст остаётся у игрока. */
    send(type, payload = {}) {
        if (!this.ws || this.ws.readyState !== 1 || !this.joined)
            return false;
        this.ws.send(JSON.stringify({ type, payload }));
        return true;
    }
    joined = false;
    open() {
        this.joined = false;
        this.o.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
        const ws = this.o.factory(this.o.url);
        this.ws = ws;
        ws.onopen = () => ws.send(JSON.stringify({ type: "auth", payload: { token: this.o.token() } }));
        ws.onmessage = (ev) => this.handle(ws, ev.data);
        ws.onclose = () => {
            if (this.ws !== ws)
                return; // закрыли сами
            this.ws = null;
            this.joined = false;
            this.o.clearTimer(this.ping);
            if (this.stopped)
                return;
            const delay = RETRY_DELAYS_MS[Math.min(this.attempt, RETRY_DELAYS_MS.length - 1)];
            this.attempt += 1;
            this.o.onStatus("reconnecting");
            this.retry = this.o.setTimer(() => !this.stopped && this.open(), delay);
        };
    }
    join(ws) {
        ws.send(JSON.stringify({ type: "campaign.join", payload: { campaign_id: this.o.campaignId, last_seq: this.lastSeq } }));
    }
    handle(ws, raw) {
        let e;
        try {
            e = JSON.parse(raw);
        }
        catch {
            return;
        }
        if (!e || typeof e.type !== "string")
            return;
        if (e.type === "auth.ok")
            return this.join(ws);
        if (e.type === "error" && e.payload.code === "unauthorized") {
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
                    if (this.ws === ws && ws.readyState === 1)
                        ws.send(JSON.stringify({ type: "ping", payload: {} }));
                    beat();
                }, PING_MS);
            };
            beat();
        }
        if (typeof e.seq === "number" && e.type !== "state.snapshot")
            this.lastSeq = Math.max(this.lastSeq ?? 0, e.seq);
        if (e.type === "state.snapshot") {
            const msgs = e.payload.messages ?? [];
            const top = Math.max(e.seq ?? 0, ...msgs.map((m) => m.seq));
            this.lastSeq = Math.max(this.lastSeq ?? 0, top);
        }
        this.o.onEvent(e);
        if (REJOIN.has(e.type) && this.joined)
            this.join(ws);
    }
}
