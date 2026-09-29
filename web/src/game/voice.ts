import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";

// Голосовые реплики: браузер записывает речь, запись уходит на сервер и в чат, локальная модель Whisper
// расшифровывает её. В чате у сообщения — плеер голоса и расшифровка; мастер работает с расшифровкой.

export const MAX_RECORD_SEC = 90;

/** Формат записи, который понимает браузер: Chrome и Firefox пишут webm/ogg, Safari — mp4. */
export function pickMime(isSupported: (t: string) => boolean): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find(isSupported);
}

/** Причина, по которой микрофон не включился, — по-русски и с тем, что делать. */
export function micError(e: unknown): string {
  const name = e instanceof DOMException || e instanceof Error ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Браузер не дал доступ к микрофону: разрешите его в настройках сайта (значок слева от адреса).";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "Микрофон не найден: подключите его и попробуйте снова.";
  if (name === "NotReadableError") return "Микрофон занят другой программой: закройте её и попробуйте снова.";
  return `Микрофон не включился: ${e instanceof Error ? e.message : String(e)}`;
}

/** Почему запись невозможна в этом браузере; null — можно. */
export function micUnsupported(): string | null {
  if (!window.isSecureContext) return "Микрофон работает только по https или на localhost.";
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined")
    return "Этот браузер не умеет записывать звук.";
  return null;
}

/** «0:07» — длительность записи. */
export function clock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

async function authed(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${getToken() ?? ""}` } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `ошибка сервера (${res.status})`);
  }
  return res;
}

/** Запись на сервер; в чат она уйдёт сообщением с этим id. */
export async function uploadVoice(campaignId: string, blob: Blob): Promise<string> {
  const res = await authed(`/api/campaigns/${campaignId}/voice`, {
    method: "POST",
    headers: { "Content-Type": blob.type || "audio/webm" },
    body: blob,
  });
  return (await res.json()).voice_id as string;
}

const urls = new Map<string, Promise<string>>();

/** Адрес записи для плеера: запрос с токеном, поэтому через blob, один раз на запись. */
export function voiceUrl(campaignId: string, voiceId: string): Promise<string> {
  let u = urls.get(voiceId);
  if (!u) {
    u = authed(`/api/campaigns/${campaignId}/voice/${voiceId}`)
      .then((r) => r.blob())
      .then((b) => URL.createObjectURL(b));
    u.catch(() => urls.delete(voiceId));
    urls.set(voiceId, u);
  }
  return u;
}

export type RecState = "idle" | "starting" | "recording";

/** Запись с микрофона. ``onClip`` получает готовую запись и её длительность. */
export function useRecorder(onClip: (blob: Blob, seconds: number) => void) {
  const [state, setState] = useState<RecState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const cancelled = useRef(false);
  const startedAt = useRef(0);
  const onClipRef = useRef(onClip);
  onClipRef.current = onClip;

  useEffect(() => {
    if (state !== "recording") return;
    setSeconds(0);
    const t = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt.current) / 1000)), 250);
    return () => clearInterval(t);
  }, [state]);

  useEffect(() => {
    if (state === "recording" && seconds >= MAX_RECORD_SEC) recorder.current?.stop();
  }, [state, seconds]);

  // уход со страницы выключает микрофон и ничего не отправляет
  useEffect(
    () => () => {
      cancelled.current = true;
      if (recorder.current?.state === "recording") recorder.current.stop();
    },
    [],
  );

  async function start() {
    const why = micUnsupported();
    if (why) {
      setError(why);
      return;
    }
    setError(null);
    setState("starting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setError(micError(e));
      setState("idle");
      return;
    }
    const mimeType = pickMime((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    cancelled.current = false;
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recorder.current = null;
      setState("idle");
      if (cancelled.current) return;
      const blob = new Blob(chunks, { type: (rec.mimeType || mimeType || "audio/webm").split(";")[0] });
      const secs = (Date.now() - startedAt.current) / 1000;
      if (!blob.size || secs < 0.5) {
        setError("Запись слишком короткая: держите микрофон включённым, пока говорите.");
        return;
      }
      onClipRef.current(blob, secs);
    };
    recorder.current = rec;
    startedAt.current = Date.now();
    rec.start();
    setState("recording");
  }

  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  function cancel() {
    cancelled.current = true;
    stop();
  }

  return { state, error, seconds, start, stop, cancel, setError };
}
