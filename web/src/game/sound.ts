// Звук сцены (design/audio-mixer.md): сервер говорит, какая музыка звучит и с какого момента, и присылает эффекты
// хода. Музыка стартует с одной позиции у всех игроков и сменяется плавно. Громкость музыки и эффектов игрок
// настраивает у себя, это хранится в браузере и на других не влияет.
import { useSyncExternalStore } from "react";
import { getToken } from "../lib/api";
import type { AudioState, AudioTrack } from "../lib/types";

export type Channel = "music" | "sfx";
export const CHANNELS: Channel[] = ["music", "sfx"];
export const CHANNEL_LABELS: Record<Channel, string> = { music: "Музыка", sfx: "Эффекты" };
const FADE = 3.5; // секунд на смену музыки
const DUCK = 0.22; // пока звучит голос мастера или игрока, музыка уходит на задний план
const PREFS_KEY = "tf_sound";

export interface Prefs {
  muted: boolean;
  master: number;
  music: number;
  sfx: number;
}

export const DEFAULT_PREFS: Prefs = { muted: false, master: 0.8, music: 1, sfx: 1 };

function clamp01(v: unknown, fallback: number): number {
  const n = typeof v === "number" ? v : Number.NaN;
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : fallback;
}

export function parsePrefs(raw: string | null): Prefs {
  let o: Record<string, unknown> = {};
  try {
    o = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
  } catch {
    o = {};
  }
  return {
    muted: o.muted === true,
    master: clamp01(o.master, DEFAULT_PREFS.master),
    music: clamp01(o.music, 1),
    sfx: clamp01(o.sfx, 1),
  };
}

/** Позиция в петле: сколько секунд петля уже звучит у всех, по модулю её длины. */
export function loopOffset(elapsed: number, duration: number): number {
  if (!(duration > 0)) return 0;
  const x = elapsed % duration;
  return x < 0 ? x + duration : x;
}

export function dbToGain(db: number | undefined): number {
  return Math.pow(10, (db ?? 0) / 20);
}

interface Voice {
  track: AudioTrack;
  source: AudioBufferSourceNode;
  gain: GainNode;
  startedAt: number; // ctx.currentTime, когда петля была на позиции offset
  offset: number;
  duration: number;
}

type Listener = () => void;

/** Один микшер на вкладку. Контекст звука создаётся только по нажатию: так требуют браузеры. */
class SoundMixer {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private buses: Partial<Record<Channel, GainNode>> = {};
  private voice: Voice | null = null;
  private buffers = new Map<string, Promise<AudioBuffer>>();
  private state: AudioState | null = null;
  private skew = 0; // часы сервера минус часы браузера, секунды
  private ducked = 0;
  private listeners = new Set<Listener>();
  private version = 0;
  prefs: Prefs = DEFAULT_PREFS;
  error: string | null = null;
  onError: (text: string) => void = () => {};

  constructor() {
    try {
      this.prefs = parsePrefs(localStorage.getItem(PREFS_KEY));
    } catch {
      this.prefs = DEFAULT_PREFS;
    }
  }

  get unlocked(): boolean {
    return this.ctx !== null && this.ctx.state === "running";
  }

  subscribe = (fn: Listener) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  snapshot = () => this.version;

  private changed() {
    this.version++;
    for (const fn of this.listeners) fn();
  }

  /** Первое нажатие «Включить звук»: создаёт контекст и сразу играет то, что уже звучит у остальных. */
  async unlock(): Promise<void> {
    if (!this.ctx) {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) throw new Error("браузер не умеет воспроизводить звук (нет Web Audio)");
      this.ctx = new Ctx();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      for (const ch of CHANNELS) {
        const g = this.ctx.createGain();
        g.connect(this.master);
        this.buses[ch] = g;
      }
      this.applyVolumes();
    }
    if (this.ctx.state !== "running") await this.ctx.resume();
    if (this.state) await this.apply(this.state);
    this.changed();
  }

  setPrefs(patch: Partial<Prefs>) {
    this.prefs = { ...this.prefs, ...patch };
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(this.prefs));
    } catch {
      /* приватный режим: настройка живёт до закрытия вкладки */
    }
    this.applyVolumes();
    this.changed();
  }

  /** Голосовое сообщение играет — музыка тише, пока оно не кончится. */
  duck(on: boolean) {
    this.ducked = Math.max(0, this.ducked + (on ? 1 : -1));
    this.applyVolumes();
  }

  private applyVolumes() {
    if (!this.ctx || !this.master) return;
    const t = this.ctx.currentTime;
    this.master.gain.setTargetAtTime(this.prefs.muted ? 0 : this.prefs.master, t, 0.1);
    for (const ch of CHANNELS) {
      const duck = this.ducked && ch === "music" ? DUCK : 1;
      // приглушение быстрое, возврат медленный: слово мастера слышно сразу, музыка возвращается незаметно
      this.buses[ch]?.gain.setTargetAtTime(this.prefs[ch] * duck, t, this.ducked ? 0.15 : 0.6);
    }
  }

  get music(): AudioTrack | null {
    return this.state?.music ?? null;
  }

  get enabled(): boolean {
    return !!this.state?.enabled;
  }

  /** Новое состояние от сервера. Пока звук не разблокирован нажатием, только запоминаем его. */
  async apply(state: AudioState): Promise<void> {
    this.skew = state.now - Date.now() / 1000;
    this.state = state;
    this.changed();
    if (!this.ctx || this.ctx.state !== "running") return;
    const want = state.enabled ? state.music : null;
    const have = this.voice;
    if (!want) {
      this.fadeOut(state.enabled ? FADE : 1.5);
      return;
    }
    if (have && have.track.id === want.id) {
      have.track = want;
      return;
    }
    try {
      await this.start(want);
    } catch (e) {
      this.report(`Звук: не играет «${want.title}»: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** Эффекты хода: один раз, поверх музыки. */
  async cue(tracks: AudioTrack[]): Promise<void> {
    if (!this.ctx || this.ctx.state !== "running" || !this.state?.enabled) return;
    for (const t of tracks) {
      try {
        const buf = await this.load(t.url);
        const src = this.ctx.createBufferSource();
        const g = this.ctx.createGain();
        src.buffer = buf;
        g.gain.value = 0.9 * dbToGain(t.gain_db);
        src.connect(g).connect(this.buses.sfx!);
        src.start();
      } catch (e) {
        this.report(`Звук: не играет «${t.title}»: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }

  private report(text: string) {
    this.error = text;
    this.changed();
    this.onError(text);
  }

  private load(url: string): Promise<AudioBuffer> {
    let p = this.buffers.get(url);
    if (!p) {
      p = (async () => {
        const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(typeof data.detail === "string" ? data.detail : `ошибка сервера (${res.status})`);
        }
        return await this.ctx!.decodeAudioData(await res.arrayBuffer());
      })();
      p.catch(() => this.buffers.delete(url));
      this.buffers.set(url, p);
    }
    return p;
  }

  private async start(track: AudioTrack) {
    const ctx = this.ctx!;
    const buf = await this.load(track.url);
    if (this.state?.music?.id !== track.id) return; // пока грузили, музыка сменилась
    const now = ctx.currentTime;
    const when = now + 0.05;
    const offset = loopOffset(Date.now() / 1000 + this.skew - (track.since ?? 0), buf.duration);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, now);
    g.gain.setTargetAtTime((track.level ?? 0.6) * dbToGain(track.gain_db), when, FADE / 3);
    src.connect(g).connect(this.buses.music!);
    src.start(when, offset);
    this.fadeOut(FADE);
    this.voice = { track, source: src, gain: g, startedAt: when, offset, duration: buf.duration };
  }

  private fadeOut(sec: number) {
    const v = this.voice;
    if (!v || !this.ctx) return;
    this.voice = null;
    const t = this.ctx.currentTime;
    v.gain.gain.cancelScheduledValues(t);
    v.gain.gain.setTargetAtTime(0, t, sec / 3);
    v.source.stop(t + sec + 0.5);
  }

  /** Уход с экрана игры: всё смолкает, контекст закрывается. */
  stop() {
    this.fadeOut(0.3);
    this.state = null;
    const ctx = this.ctx;
    this.ctx = null;
    this.master = null;
    this.buses = {};
    this.buffers.clear();
    if (ctx) window.setTimeout(() => void ctx.close(), 800);
    this.changed();
  }
}

export const sound = new SoundMixer();

/** Перерисовка при любом изменении микшера: состояние, громкость, разблокировка. */
export function useSound(): SoundMixer {
  useSyncExternalStore(sound.subscribe, sound.snapshot);
  return sound;
}
