// Звук сцены (design/audio-mixer.md): сервер говорит, какая музыка звучит и с какого момента, и присылает эффекты
// хода. Музыка стартует с одной позиции у всех игроков и сменяется плавно. Громкость музыки и эффектов игрок
// настраивает у себя, это хранится в браузере и на других не влияет.
import { useSyncExternalStore } from "react";
import { getToken } from "../lib/api";
import type { AudioSfxReady, AudioState, AudioTrack, Scene } from "../lib/types";
import { prepareMusic, primeMusic, type MusicDeck, type PreparedMusic } from "./music";

export type Channel = "music" | "sfx";
export const CHANNELS: Channel[] = ["music", "sfx"];
export const CHANNEL_LABELS: Record<Channel, string> = { music: "Музыка", sfx: "Эффекты" };
const FADE = 3.5; // секунд на смену музыки
const SURFACE_FADE = 0.5;
const QUIET_FADE = 0.15;
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

export type AudioSurface = "menu" | "scene" | "silent";
export interface MenuMusicPreferences {
  enabled: boolean;
  volume: number;
}
type MenuStatus = "disabled" | "locked" | "loading" | "playing" | "paused" | "error";

interface Voice extends PreparedMusic {
  track: AudioTrack;
  deck: MusicDeck;
  kind: "scene" | "menu";
}

type Listener = () => void;

/** Bounded deduplication plus a context guard that remains valid while audio is loading. */
export class SfxGate {
  private seen = new Set<string>();
  private revision = 0;
  private context: Pick<Scene, "mode" | "round" | "location" | "party"> | null = null;
  private allPlaces = false;

  scene(scene: Pick<Scene, "mode" | "round" | "location" | "party"> | null, allPlaces = false) {
    this.context = scene;
    this.allPlaces = allPlaces;
    this.revision++;
  }

  accept(event: AudioSfxReady, now: number): ((now: number) => boolean) | null {
    if (this.seen.has(event.event_id)) return null;
    this.seen.add(event.event_id);
    if (this.seen.size > 256) this.seen.delete(this.seen.values().next().value!);
    const revision = this.revision;
    const valid = (at: number) => {
      const context = this.context;
      const place = context?.location?.id ?? null;
      const matches = event.place_id === place || (
        this.allPlaces && context?.party?.some((p) => p.id === event.place_id)
      );
      return !!context && revision === this.revision && matches === true && at < event.expires_at
        && context.mode === event.mode && context.round === event.round;
    };
    return valid(now) ? valid : null;
  }

  clear() { this.scene(null); this.seen.clear(); }
}

/** Один микшер на вкладку. Контекст звука создаётся только по нажатию: так требуют браузеры. */
export class SoundMixer {
  private generatedGate = new SfxGate();
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private menuBus: GainNode | null = null;
  private buses: Partial<Record<Channel, GainNode>> = {};
  private voice: Voice | null = null;
  private decks: MusicDeck[] = [];
  private musicReady: Promise<void> | null = null;
  private musicPrimed = false;
  private musicLoad: AbortController | null = null;
  private starting: string | null = null;
  private fading = new Map<Voice, ReturnType<typeof setTimeout>>();
  private buffers = new Map<string, Promise<AudioBuffer>>();
  private state: AudioState | null = null;
  private surface: AudioSurface = "scene";
  private menuTrack: AudioTrack | null = null;
  private menuPrefs: MenuMusicPreferences = { enabled: true, volume: 0.2 };
  private menuOffset = 0;
  private visible = true;
  private targetRevision = 0;
  private _menuStatus: MenuStatus = "disabled";
  private _menuError: string | null = null;
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
    return this.musicPrimed && this.ctx !== null && this.ctx.state === "running";
  }

  get menuStatus(): MenuStatus { return this._menuStatus; }
  get menuError(): string | null { return this._menuError; }
  get menuTheme(): AudioTrack | null { return this.menuTrack; }
  get audioSurface(): AudioSurface { return this.surface; }

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
      this.menuBus = this.ctx.createGain();
      this.menuBus.connect(this.ctx.destination);
      for (const ch of CHANNELS) {
        const g = this.ctx.createGain();
        g.connect(this.master);
        this.buses[ch] = g;
      }
      this.applyVolumes();
      const primed = primeMusic(this.ctx);
      this.decks = primed.decks;
      this.musicReady = primed.ready;
    }
    const ctx = this.ctx;
    try {
      await Promise.all([ctx.state === "running" ? Promise.resolve() : ctx.resume(), this.musicReady]);
      if (this.ctx !== ctx) return;
      this.musicPrimed = true;
    } catch (e) {
      if (this.ctx === ctx) {
        this.releaseAudioResources();
        this.changed();
      }
      throw e;
    }
    await this.reconcile();
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

  async setSurface(surface: AudioSurface): Promise<void> {
    if (this.surface === surface) return;
    this.surface = surface;
    this.targetRevision++;
    this.musicLoad?.abort();
    this.musicLoad = null;
    this.starting = null;
    if (surface !== "menu" && this.menuTrack && this.menuPrefs.enabled && this.menuPrefs.volume > 0) {
      this._menuStatus = "paused";
    }
    await this.reconcile();
    this.changed();
  }

  async setMenuMusic(track: AudioTrack | null, prefs: MenuMusicPreferences): Promise<void> {
    this.menuTrack = track;
    this.menuPrefs = { enabled: prefs.enabled, volume: Math.max(0, Math.min(1, prefs.volume)) };
    this.targetRevision++;
    this.musicLoad?.abort();
    this.musicLoad = null;
    this.starting = null;
    this._menuError = null;
    if (!track || !this.menuPrefs.enabled || this.menuPrefs.volume <= 0) this._menuStatus = "disabled";
    else if (!this.unlocked) this._menuStatus = "locked";
    await this.reconcile();
    if (this.voice?.kind === "menu" && this.voice.track.id === track?.id && this.menuPrefs.enabled) {
      this.voice.gain.gain.setTargetAtTime(this.menuPrefs.volume, this.ctx?.currentTime ?? 0, 0.1);
    }
    this.changed();
  }

  async setDocumentVisible(visible: boolean): Promise<void> {
    this.visible = visible;
    if (!visible && this.surface === "menu") {
      this.targetRevision++;
      this.musicLoad?.abort();
      this.musicLoad = null;
      this.starting = null;
      if (this.menuTrack && this.menuPrefs.enabled && this.menuPrefs.volume > 0) this._menuStatus = "paused";
      await this.fadeOut(QUIET_FADE);
    } else if (visible) {
      await this.reconcile();
    }
    this.changed();
  }

  private async reconcile(): Promise<void> {
    if (!this.unlocked) {
      if (this.surface === "menu" && this.menuTrack && this.menuPrefs.enabled && this.menuPrefs.volume > 0) {
        this._menuStatus = "locked";
      }
      return;
    }
    if (this.surface === "silent") {
      await this.fadeOut(QUIET_FADE);
      return;
    }
    if (this.surface === "menu") {
      const track = this.menuTrack;
      if (!track || !this.menuPrefs.enabled || this.menuPrefs.volume <= 0) {
        this._menuStatus = "disabled";
        await this.fadeOut(QUIET_FADE);
        return;
      }
      if (!this.visible) {
        this._menuStatus = "paused";
        await this.fadeOut(QUIET_FADE);
        return;
      }
      if (this.voice?.kind === "menu" && this.voice.track.id === track.id) {
        this._menuStatus = "playing";
        return;
      }
      if (this.voice) await this.fadeOut(SURFACE_FADE);
      this._menuStatus = "loading";
      try {
        await this.start(track, "menu", this.menuPrefs.volume, this.menuOffset, SURFACE_FADE, this.targetRevision);
        if (this.surface === "menu" && this.visible && this.menuTrack?.id === track.id
          && this.menuPrefs.enabled && this.menuPrefs.volume > 0 && this.voice?.kind === "menu") {
          this._menuStatus = "playing";
        }
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          this._menuError = e instanceof Error ? e.message : String(e);
          this._menuStatus = "error";
        }
      }
      return;
    }
    const want = this.state?.enabled ? this.state.music : null;
    if (!want) {
      await this.fadeOut(this.state?.enabled ? FADE : QUIET_FADE);
      return;
    }
    if (this.voice?.kind === "scene" && this.voice.track.id === want.id) {
      this.voice.track = want;
      return;
    }
    if (this.voice?.kind === "menu") await this.fadeOut(SURFACE_FADE);
    if (this.starting === want.id) return;
    try {
      await this.start(want, "scene", want.level ?? 0.6,
        Date.now() / 1000 + this.skew - (want.since ?? 0), FADE, this.targetRevision);
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        this.report(`Звук: не играет «${want.title}»: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }

  /** Новое состояние от сервера. Пока звук не разблокирован нажатием, только запоминаем его. */
  async apply(state: AudioState): Promise<void> {
    this.skew = state.now - Date.now() / 1000;
    this.state = state;
    this.changed();
    this.targetRevision++;
    if (!this.unlocked || this.surface !== "scene") return;
    this.musicLoad?.abort();
    this.musicLoad = null;
    this.starting = null;
    await this.reconcile();
  }

  /** Эффекты хода: один раз, поверх музыки. */
  async cue(tracks: AudioTrack[], valid: () => boolean = () => true): Promise<void> {
    if (this.surface !== "scene" || !this.ctx || this.ctx.state !== "running" || !this.state?.enabled || this.prefs.muted) return;
    const ctx = this.ctx;
    for (const t of tracks) {
      try {
        const buf = await this.load(t.url);
        if (this.ctx !== ctx || ctx.state !== "running" || !this.state?.enabled || this.prefs.muted || !valid()) return;
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

  setScene(scene: Scene | null, allPlaces = false) {
    this.generatedGate.scene(scene, allPlaces);
  }

  async generated(event: AudioSfxReady): Promise<void> {
    if (this.surface !== "scene") return;
    const now = () => Date.now() / 1000 + this.skew;
    const valid = this.generatedGate.accept(event, now());
    if (valid) await this.cue([event.track], () => valid(now()));
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
      if (this.buffers.size > 32) this.buffers.delete(this.buffers.keys().next().value!);
    }
    return p;
  }

  private async start(
    track: AudioTrack,
    kind: "scene" | "menu",
    level: number,
    offset: number,
    fade: number,
    revision: number,
  ) {
    const ctx = this.ctx!;
    const controller = new AbortController();
    this.musicLoad?.abort();
    this.musicLoad = controller;
    this.starting = track.id;
    const deck = this.decks.find((d) => d !== this.voice?.deck)!;
    for (const [voice, timer] of this.fading) {
      if (voice.deck === deck) {
        clearTimeout(timer);
        voice.dispose();
        this.fading.delete(voice);
      }
    }
    let music: PreparedMusic | undefined;
    try {
      music = await prepareMusic(ctx, track.url, getToken() ?? "", controller.signal, deck);
      controller.signal.throwIfAborted();
      if (this.targetRevision !== revision ||
        (kind === "scene"
          ? this.surface !== "scene" || !this.state?.enabled || this.state.music?.id !== track.id
          : this.surface !== "menu" || !this.visible || this.menuTrack?.id !== track.id
            || !this.menuPrefs.enabled || this.menuPrefs.volume <= 0)) {
        music.dispose();
        return;
      }
      const now = ctx.currentTime;
      music.gain.gain.setValueAtTime(0, now);
      music.gain.connect(kind === "menu" ? this.menuBus! : this.buses.music!);
      music.element.currentTime = kind === "menu"
        ? loopOffset(offset, music.element.duration)
        : loopOffset(offset, music.element.duration);
      await music.element.play();
      controller.signal.throwIfAborted();
      if (this.ctx !== ctx || this.targetRevision !== revision ||
        (kind === "scene"
          ? this.surface !== "scene" || !this.state?.enabled || this.state.music?.id !== track.id
          : this.surface !== "menu" || !this.visible || this.menuTrack?.id !== track.id
            || !this.menuPrefs.enabled || this.menuPrefs.volume <= 0)) {
        music.dispose();
        return;
      }
      music.gain.gain.setTargetAtTime(level * dbToGain(track.gain_db), ctx.currentTime, fade / 3);
      await this.fadeOut(fade);
      this.voice = { ...music, track, deck, kind };
      this.error = null;
      if (kind === "menu") this._menuError = null;
      this.changed();
    } catch (e) {
      music?.dispose();
      if (controller.signal.aborted) return;
      throw e;
    } finally {
      if (this.musicLoad === controller) {
        this.musicLoad = null;
        this.starting = null;
      }
    }
  }

  private async fadeOut(sec: number): Promise<void> {
    const v = this.voice;
    if (!v || !this.ctx) return;
    this.voice = null;
    if (v.kind === "menu") this.menuOffset = v.element.currentTime || this.menuOffset;
    const t = this.ctx.currentTime;
    v.gain.gain.cancelScheduledValues(t);
    v.gain.gain.setTargetAtTime(0, t, sec / 3);
    const timer = setTimeout(() => {
      v.dispose();
      this.fading.delete(v);
    }, (sec + 0.5) * 1000);
    this.fading.set(v, timer);
  }

  /** Уход со сцены: состояние и эффекты очищаются, контекст приложения остаётся разблокированным. */
  clearScene() {
    this.targetRevision++;
    this.musicLoad?.abort();
    this.musicLoad = null;
    this.starting = null;
    if (this.voice?.kind === "scene") void this.fadeOut(QUIET_FADE);
    this.state = null;
    this.skew = 0;
    this.generatedGate.clear();
    this.changed();
  }

  private releaseAudioResources() {
    this.musicLoad?.abort();
    this.musicLoad = null;
    this.starting = null;
    this.voice?.dispose();
    this.voice = null;
    for (const [voice, timer] of this.fading) {
      clearTimeout(timer);
      voice.dispose();
    }
    this.fading.clear();
    for (const deck of this.decks) {
      deck.element.pause();
      deck.element.removeAttribute("src");
      deck.element.load();
      deck.source.disconnect();
    }
    this.decks = [];
    this.musicReady = null;
    this.musicPrimed = false;
    const ctx = this.ctx;
    this.ctx = null;
    this.master = null;
    this.menuBus = null;
    this.buses = {};
    this.buffers.clear();
    if (ctx) window.setTimeout(() => void ctx.close(), 800);
  }

  /** Полный teardown при выходе из аккаунта или уничтожении приложения. */
  stop() {
    this.releaseAudioResources();
    this.state = null;
    this.surface = "silent";
    this.menuTrack = null;
    this.menuOffset = 0;
    this.menuPrefs = { enabled: true, volume: 0.2 };
    this._menuStatus = "disabled";
    this._menuError = null;
    this.generatedGate.clear();
    this.changed();
  }
}

export const sound = new SoundMixer();

/** Перерисовка при любом изменении микшера: состояние, громкость, разблокировка. */
export function useSound(): SoundMixer {
  useSyncExternalStore(sound.subscribe, sound.snapshot);
  return sound;
}
