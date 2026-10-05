import { useEffect, useRef, useState } from "react";
import type { VoiceData } from "../lib/types";
import { useGame } from "../stores/game";
import { sound } from "./sound";
import { claimAutoplay, clock, voiceUrl } from "./voice";

/** Кто сейчас звучит; остальные автозапуски ждут своей очереди, чтобы голоса не перебивали друг друга. */
let speaking: { stop: () => void } | null = null;
const queue: (() => void)[] = [];
const WAIT_PART_MS = 90_000; // следующая часть озвучки не пришла за это время — отпускаем очередь

/** Ручной запуск перебивает того, кто звучит; очередь автозапусков при этом не трогается. */
function takeOver(who: { stop: () => void }) {
  const prev = speaking;
  speaking = who;
  if (prev && prev !== who) prev.stop();
}

function release(who: { stop: () => void }) {
  if (speaking !== who) return;
  speaking = null;
  queue.shift()?.();
}

/** Плеер голосовой реплики: живой голос автора или мастера. Длинное повествование озвучено частями (clips):
 * они играют подряд одной дорожкой; expected — сколько частей ждать, если не все ещё готовы. */
export default function VoiceClip({ clips, expected, autoPlay }: { clips: VoiceData[]; expected?: number; autoPlay?: boolean }) {
  const campaignId = useGame((s) => s.snapshot?.campaign.id);
  const audios = useRef(new Map<string, HTMLAudioElement>());
  const [state, setState] = useState<"idle" | "loading" | "playing" | "waiting">("idle");
  const [error, setError] = useState<string | null>(null);
  const [part, setPart] = useState(0);
  const [pos, setPos] = useState(0);
  const total = Math.max(expected ?? 0, clips.length);
  const latest = useRef({ clips, total });
  latest.current = { clips, total };
  const me = useRef({ stop: () => stop() });
  const waitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const waitingFor = useRef(0);

  const ducking = useRef(false);
  // пока звучит голос мастера или игрока, музыка сцены тише
  const duck = (on: boolean) => {
    if (ducking.current === on) return;
    ducking.current = on;
    sound.duck(on);
  };
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      for (const a of audios.current.values()) a.pause();
      if (waitTimer.current) clearTimeout(waitTimer.current);
      if (ducking.current) sound.duck(false);
      release(me.current);
    };
  }, []);

  function stop() {
    audios.current.forEach((a) => a.pause());
    if (waitTimer.current) clearTimeout(waitTimer.current);
    setState("idle");
    duck(false);
    release(me.current);
  }

  function finish() {
    setState("idle");
    setPart(0);
    setPos(0);
    duck(false);
    release(me.current);
  }

  async function audioFor(clip: VoiceData): Promise<HTMLAudioElement> {
    let a = audios.current.get(clip.id);
    if (a) return a;
    const url = await voiceUrl(campaignId!, clip.id);
    a = new Audio(url);
    a.ontimeupdate = () => setPos(a!.currentTime);
    audios.current.set(clip.id, a);
    return a;
  }

  /** Играет часть i; конец части запускает следующую или ждёт, пока она озвучится. */
  async function playPart(i: number) {
    const { clips: list, total: want } = latest.current;
    if (i >= list.length) {
      if (i < want) {
        waitingFor.current = i;
        setState("waiting"); // музыка остаётся тише: следующая часть вот-вот прозвучит
        if (waitTimer.current) clearTimeout(waitTimer.current);
        waitTimer.current = setTimeout(finish, WAIT_PART_MS);
      } else finish();
      return;
    }
    setError(null);
    setPart(i);
    try {
      if (!audios.current.has(list[i].id)) setState("loading");
      const a = await audioFor(list[i]);
      if (!alive.current) return; // пока грузилась запись, плеер убрали с экрана: играть некому
      a.onended = () => {
        setPos(0);
        void playPart(i + 1);
      };
      a.onpause = () => {
        if (!a.ended) setState((s) => (s === "playing" ? "idle" : s));
      };
      a.onplay = () => {
        setState("playing");
        duck(true);
      };
      takeOver(me.current);
      await a.play();
    } catch (e) {
      setState("idle");
      release(me.current);
      if (e instanceof Error && e.name === "NotAllowedError") return;
      setError(`Не проигрывается: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // ждали следующую часть — она пришла: играем дальше
  useEffect(() => {
    if (state === "waiting" && clips.length > waitingFor.current) {
      if (waitTimer.current) clearTimeout(waitTimer.current);
      void playPart(waitingFor.current);
    } else if (state === "waiting" && clips.length >= total) finish(); // недостающие части так и не озвучились
  }, [clips.length, total]);

  // свежая реплика играет сама, один раз; если кто-то уже звучит — после него
  const first = clips[0]?.id;
  useEffect(() => {
    if (!autoPlay || !campaignId || !first || !claimAutoplay(first)) return;
    const start = () => {
      if (alive.current) void playPart(0);
      else queue.shift()?.(); // плеер уже убран с экрана: очередь идёт дальше
    };
    if (speaking) queue.push(start);
    else start();
  }, [autoPlay, campaignId, first]);

  async function toggle() {
    if (state === "playing" || state === "waiting") {
      stop();
      return;
    }
    const cur = clips[part] && audios.current.get(clips[part].id);
    if (cur && cur.currentTime > 0 && !cur.ended) {
      takeOver(me.current);
      try {
        await cur.play();
      } catch (e) {
        setError(`Не проигрывается: ${e instanceof Error ? e.message : String(e)}`);
      }
      return;
    }
    await playPart(part < clips.length ? part : 0);
  }

  const durations = clips.map((c) => c.duration ?? 0);
  const known = durations.reduce((a, b) => a + b, 0);
  const done = durations.slice(0, part).reduce((a, b) => a + b, 0) + pos;
  const pending = clips.length < total;
  const progress = known ? Math.min(1, done / known) : 0;
  const busy = state === "loading" || state === "waiting";
  const label = !clips.length
    ? "Озвучка готовится"
    : state === "playing"
      ? "Пауза"
      : state === "waiting"
        ? "Следующая часть озвучки готовится"
        : "Прослушать голосовое";
  return (
    <div className="mb-1 flex flex-col gap-1">
      <button
        type="button"
        onClick={toggle}
        disabled={!clips.length}
        className="flex w-56 max-w-full items-center gap-2 rounded-full border border-line bg-surface px-2 py-1 text-xs disabled:opacity-70"
        aria-label={label}
        title={label}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-[11px] text-bg">
          {busy || !clips.length ? "…" : state === "playing" ? "❚❚" : "▶"}
        </span>
        <span className="relative h-1 flex-1 overflow-hidden rounded-full bg-raised">
          <span className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${progress * 100}%` }} />
        </span>
        <span className="font-mono text-muted">
          {clock(state === "playing" || done ? done : known)}
          {pending ? "+" : ""}
        </span>
      </button>
      {!clips.length && <p className="text-xs text-muted">Озвучка готовится…</p>}
      {pending && clips.length > 0 && (
        <p className="text-xs text-muted">
          Озвучено частей: {clips.length} из {total}, остальные готовятся и зазвучат следом
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-warn">
          {error}
        </p>
      )}
    </div>
  );
}
