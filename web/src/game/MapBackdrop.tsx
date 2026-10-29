import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useAuthedImage } from "../lib/authedImage";

interface Artwork {
  status: "idle" | "pending" | "ready" | "failed";
  image_url: string | null;
  stale: boolean;
  enabled: boolean;
  can_generate: boolean;
  error: string | null;
}

export interface MapBackdropState {
  artwork: Artwork | null;
  busy: boolean;
  error: string;
  loadError: string;
  generate: (regenerate?: boolean) => Promise<void>;
  retry: () => void;
}

/** Статус и ручной запуск подложки области. Родитель задаёт key по области: поздние ответы старой области не подменяют новую. */
export function useMapBackdrop(campaignId: string, locationId: string): MapBackdropState {
  const endpoint = `/api/campaigns/${campaignId}/locations/${locationId}/map-backdrop`;
  const [artwork, setArtwork] = useState<Artwork | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const active = useRef(true);
  const running = useRef(false);
  const requestKey = useRef<string | null>(null);

  useEffect(() => {
    active.current = true;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const data = await api<Artwork>(endpoint);
        if (!alive) return;
        setArtwork(data);
        setLoadError("");
        if (data.status === "ready") setError("");
        if (data.status === "failed") requestKey.current = null;
        if (data.enabled) timer = setTimeout(() => void load(), data.status === "pending" ? 2500 : 15000);
      } catch {
        if (alive) {
          setLoadError("Не удалось проверить подложку карты.");
          timer = setTimeout(() => void load(), 5000);
        }
      }
    };
    void load();
    return () => {
      alive = false;
      active.current = false;
      clearTimeout(timer);
    };
  }, [endpoint, refresh]);

  const generate = async (regenerate = false) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    if (!requestKey.current || regenerate) requestKey.current = crypto.randomUUID();
    try {
      const data = await api<Artwork>(endpoint, { body: { request_key: requestKey.current, regenerate } });
      if (!active.current) return;
      setArtwork(data);
      requestKey.current = null;
    } catch (e) {
      if (!active.current) return;
      const pending = e instanceof ApiError && (e.data as { detail?: { code?: string } })?.detail?.code === "artwork_pending";
      if (!pending) {
        setError(e instanceof Error ? e.message : "Не удалось создать подложку.");
        if (e instanceof ApiError && e.status < 500 && e.status !== 408) requestKey.current = null;
      }
    } finally {
      running.current = false;
      if (active.current) {
        setBusy(false);
        setRefresh((v) => v + 1);
      }
    }
  };

  return { artwork, busy, error, loadError, generate, retry: () => setRefresh((v) => v + 1) };
}

/** Кнопка и статус подложки; участники без права запуска ничего не видят, кроме сообщений об ошибке. */
export function BackdropControls({ backdrop }: { backdrop: MapBackdropState }) {
  const { artwork, busy, error, loadError, generate, retry } = backdrop;
  if (!artwork || (!artwork.enabled && !artwork.image_url)) return null;
  const pending = busy || artwork.status === "pending";
  const message = error || artwork.error;
  const run = (regenerate: boolean) => () => void generate(regenerate);
  const label = !artwork.image_url
    ? pending ? "Создаю подложку…" : "Создать подложку"
    : artwork.stale
      ? pending ? "Обновляю подложку…" : "Обновить подложку для новой схемы"
      : pending ? "Создаю новую подложку…" : "↻ Пересоздать подложку";
  return (
    <div className="space-y-1" aria-label="Подложка карты">
      {artwork.can_generate && (
        <button type="button" disabled={pending} onClick={run(Boolean(artwork.image_url))} className="btn-ghost w-full py-2 text-xs">
          {label}
        </button>
      )}
      {artwork.image_url && artwork.stale && <p className="text-[11px] text-muted">Подложка устарела: описание или схема изменились.</p>}
      {pending && <p role="status" className="text-[11px] text-muted">Рисую подложку… Можно продолжать игру.</p>}
      {message && <p role="alert" className="text-[11px] text-bad">{message}</p>}
      {loadError && !message && (
        <div role="alert" className="text-[11px] text-muted">
          <span>{loadError}</span>
          <button type="button" onClick={retry} className="ml-2 underline text-ink hover:text-accent">Повторить проверку</button>
        </div>
      )}
    </div>
  );
}

/** Картина на всю сетку области; клики остаются на слоях выше. Края обрезаются: у модели по краям тёмная каёмка. */
export const BACKDROP_CROP = 0.04;

export function BackdropLayer({ url, cols, rows }: { url: string; cols: number; rows: number }) {
  const src = useAuthedImage(url);
  if (!src) return null;
  const inner = 1 - 2 * BACKDROP_CROP;
  return (
    <svg data-map-backdrop="true" x={0} y={0} width={cols} height={rows} viewBox={`${BACKDROP_CROP} ${BACKDROP_CROP} ${inner} ${inner}`} preserveAspectRatio="none" pointerEvents="none">
      <image href={src} x={0} y={0} width={1} height={1} preserveAspectRatio="none" />
    </svg>
  );
}
