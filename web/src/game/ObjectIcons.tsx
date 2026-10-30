import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useAuthedImage } from "../lib/authedImage";

interface IconItem {
  id: string;
  name: string;
  status: "idle" | "pending" | "ready" | "failed";
  image_url: string | null;
  stale: boolean;
  enabled: boolean;
  can_generate: boolean;
  error: string | null;
}
interface IconList { enabled: boolean; can_generate: boolean; objects: IconItem[] }

export interface ObjectIconsState {
  list: IconList | null;
  /** id предмета → адрес его значка; только готовые. */
  urls: Record<string, string>;
  missing: IconItem[];
  busy: boolean;
  progress: { done: number; total: number } | null;
  error: string;
  drawMissing: () => Promise<void>;
}

/** Значки предметов области. Родитель задаёт key по области: поздние ответы старой области не подменяют новую. */
export function useObjectIcons(campaignId: string, locationId: string): ObjectIconsState {
  const listUrl = `/api/campaigns/${campaignId}/locations/${locationId}/object-icons`;
  const [list, setList] = useState<IconList | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ObjectIconsState["progress"]>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const active = useRef(true);
  const running = useRef(false);

  useEffect(() => {
    active.current = true;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const data = await api<IconList>(listUrl);
        if (!alive) return;
        setList(data);
        if (data.enabled) timer = setTimeout(() => void load(), 15000);
      } catch {
        if (alive) timer = setTimeout(() => void load(), 5000);
      }
    };
    void load();
    return () => { alive = false; active.current = false; clearTimeout(timer); };
  }, [listUrl, refresh]);

  const drawMissing = async () => {
    if (running.current || !list) return;
    const todo = list.objects.filter((o) => o.can_generate && o.status !== "ready");
    if (!todo.length) return;
    running.current = true;
    setBusy(true);
    setError("");
    const failed: string[] = [];
    for (const [index, object] of todo.entries()) {
      if (!active.current) break;
      setProgress({ done: index, total: todo.length });
      try {
        const done = await api<IconItem>(`/api/campaigns/${campaignId}/objects/${object.id}/icon`, {
          body: { request_key: crypto.randomUUID(), regenerate: false },
        });
        if (active.current) setList((current) => current && { ...current, objects: current.objects.map((o) => (o.id === object.id ? { ...o, ...done } : o)) });
      } catch (e) {
        const pending = e instanceof ApiError && (e.data as { detail?: { code?: string } })?.detail?.code === "artwork_pending";
        if (!pending) failed.push(object.name);
      }
    }
    running.current = false;
    if (!active.current) return;
    setBusy(false);
    setProgress(null);
    if (failed.length) setError(`Не удалось нарисовать значки: ${failed.join(", ")}. Можно повторить.`);
    setRefresh((v) => v + 1);
  };

  const urls: Record<string, string> = {};
  for (const object of list?.objects ?? []) if (object.status === "ready" && object.image_url) urls[object.id] = object.image_url;
  const missing = (list?.objects ?? []).filter((o) => o.can_generate && o.status !== "ready");
  return { list, urls, missing, busy, progress, error, drawMissing };
}

/** Кнопка пакетной генерации; видна только тому, кто может запускать, и только пока есть предметы без значка. */
export function ObjectIconControls({ icons }: { icons: ObjectIconsState }) {
  const { list, missing, busy, progress, error, drawMissing } = icons;
  if (!list || !list.enabled) return null;
  const showButton = list.can_generate && (missing.length > 0 || busy);
  if (!showButton && !error) return null;
  return (
    <div className="space-y-1" aria-label="Значки предметов">
      {showButton && (
        <button type="button" disabled={busy} onClick={() => void drawMissing()} className="btn-ghost w-full py-2 text-xs">
          {busy ? `Рисую значки: ${progress ? progress.done + 1 : 1} из ${progress?.total ?? missing.length}…` : `Нарисовать значки предметов (${missing.length})`}
        </button>
      )}
      {error && <p role="alert" className="text-[11px] text-bad">{error}</p>}
    </div>
  );
}

/** Нарисованный значок предмета в круглой метке на карте. */
export function ObjectIconImage({ url, cx, cy, r }: { url: string; cx: number; cy: number; r: number }) {
  const src = useAuthedImage(url);
  if (!src) return null;
  const clip = `object-icon-clip-${cx}-${cy}`;
  return (
    <>
      <clipPath id={clip}><circle cx={cx} cy={cy} r={r} /></clipPath>
      <image href={src} x={cx - r} y={cy - r} width={r * 2} height={r * 2} preserveAspectRatio="xMidYMid slice" clipPath={`url(#${clip})`} />
    </>
  );
}
