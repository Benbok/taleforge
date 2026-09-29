import { useEffect, useRef, useState } from "react";
import type { VoiceData } from "../lib/types";
import { useGame } from "../stores/game";
import { sound } from "./sound";
import { clock, voiceUrl } from "./voice";

/** Плеер голосовой реплики: живой голос автора. Играет только по нажатию — без какофонии за столом. */
export default function VoiceClip({ clip }: { clip: VoiceData }) {
  const campaignId = useGame((s) => s.snapshot?.campaign.id);
  const audio = useRef<HTMLAudioElement | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [pos, setPos] = useState(0);

  const ducking = useRef(false);
  // пока звучит голос игрока, музыка сцены тише
  const duck = (on: boolean) => {
    if (ducking.current === on) return;
    ducking.current = on;
    sound.duck(on);
  };
  useEffect(
    () => () => {
      audio.current?.pause();
      if (ducking.current) sound.duck(false);
    },
    [],
  );

  async function toggle() {
    if (state === "playing") {
      audio.current?.pause();
      return;
    }
    if (!campaignId) return;
    setError(null);
    try {
      if (!audio.current) {
        setState("loading");
        const a = new Audio(await voiceUrl(campaignId, clip.id));
        a.ontimeupdate = () => setPos(a.currentTime);
        a.onpause = () => {
          setState("idle");
          duck(false);
        };
        a.onended = () => {
          setState("idle");
          setPos(0);
          duck(false);
        };
        a.onplay = () => {
          setState("playing");
          duck(true);
        };
        audio.current = a;
      }
      await audio.current.play();
    } catch (e) {
      setState("idle");
      setError(`Не проигрывается: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const total = clip.duration ?? 0;
  const progress = total ? Math.min(1, pos / total) : 0;
  return (
    <div className="mb-1 flex flex-col gap-1">
      <button
        type="button"
        onClick={toggle}
        className="flex w-56 max-w-full items-center gap-2 rounded-full border border-line bg-surface px-2 py-1 text-xs"
        aria-label={state === "playing" ? "Пауза" : "Прослушать голосовое"}
        title={state === "playing" ? "Пауза" : "Прослушать голосовое"}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-[11px] text-bg">
          {state === "loading" ? "…" : state === "playing" ? "❚❚" : "▶"}
        </span>
        <span className="relative h-1 flex-1 overflow-hidden rounded-full bg-raised">
          <span className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${progress * 100}%` }} />
        </span>
        <span className="font-mono text-muted">{clock(state === "playing" || pos ? pos : total)}</span>
      </button>
      {error && (
        <p role="alert" className="text-xs text-warn">
          {error}
        </p>
      )}
    </div>
  );
}
