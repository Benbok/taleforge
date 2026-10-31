import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import CampaignCoverImage from "../components/CampaignCoverImage";
import { api, ApiError } from "../lib/api";

interface Cover {
  status: "idle" | "pending" | "ready" | "failed";
  image_url: string | null;
  thumbnail_url: string | null;
  inherited?: boolean;
  stale: boolean;
  enabled: boolean;
  can_generate: boolean;
  error: string | null;
}

/**
 * Обложка мира: создаётся только кнопкой владельца; прежняя картинка остаётся, пока идёт замена или она не удалась.
 * Один компонент на два места: настройки кампании (`/api/campaigns/<id>/cover`) и студия мира (`/api/author/projects/<id>/cover`).
 */
export default function CampaignCoverStudio({
  endpoint,
  name,
  unsaved,
  scope = "campaign",
}: {
  endpoint: string;
  name: string;
  unsaved: boolean;
  scope?: "campaign" | "world";
}) {
  const queryClient = useQueryClient();
  const world = scope === "world";
  const key = ["campaign-cover", endpoint];
  const cover = useQuery({
    queryKey: key,
    queryFn: () => api<Cover>(endpoint),
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 2500 : false),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  // Ключ переживает неопределённую ошибку сети: повтор не оплачивает вторую картинку.
  const requestKey = useRef<string | null>(null);

  const art = cover.data;
  if (!art || (!art.enabled && !art.image_url)) return null;

  async function generate(regenerate: boolean) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    if (!requestKey.current || regenerate) requestKey.current = crypto.randomUUID();
    try {
      const next = await api<Cover>(endpoint, { body: { request_key: requestKey.current, regenerate } });
      queryClient.setQueryData(key, next);
      requestKey.current = null;
      void queryClient.invalidateQueries({ queryKey: ["my-campaigns"] });
      if (world) void queryClient.invalidateQueries({ queryKey: ["library"] });
    } catch (e) {
      const pending = e instanceof ApiError && (e.data as { detail?: { code?: string } })?.detail?.code === "artwork_pending";
      if (!pending) {
        setError(e instanceof Error ? e.message : "Не удалось создать обложку.");
        // Ответ сервера (4xx) закрывает попытку; сетевая ошибка и 5xx оставляют ключ для безопасного повтора.
        if (e instanceof ApiError && e.status < 500 && e.status !== 408) requestKey.current = null;
      }
    } finally {
      running.current = false;
      setBusy(false);
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const pending = busy || art.status === "pending";
  const blocked = pending || unsaved || !art.can_generate;
  const own = Boolean(art.image_url) && !art.inherited;
  const label = own ? (art.stale ? "Обновить обложку" : "Пересоздать обложку") : art.inherited ? "Создать свою обложку" : "Создать обложку";
  const message = error || art.error;

  return (
    <section className="card flex flex-col gap-4 border border-line bg-surface p-5 sm:p-6" aria-label="Обложка мира">
      <div className="border-b border-line pb-3">
        <h2 className="font-heading text-xl font-bold text-ink">Обложка мира</h2>
        <p className="text-xs text-muted">
          {world
            ? "Широкая иллюстрация мира. Рисуется по названию и публичному тексту, без тайн. Её получают все столы этого мира."
            : "Широкая иллюстрация для главной страницы. Рисуется по названию и публичной вводной, без тайн кампании."}
        </p>
      </div>

      {art.image_url ? (
        <CampaignCoverImage
          url={art.image_url}
          name={name}
          className="aspect-video w-full rounded-xl border border-line-soft"
          expandable
        />
      ) : (
        <div className="flex aspect-video w-full items-center justify-center rounded-xl border border-dashed border-line bg-surface-2 px-4 text-center text-sm text-muted">
          Обложки пока нет
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn btn-outline-copper px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          disabled={blocked}
          onClick={() => void generate(own)}
        >
          {pending ? (art.image_url ? "Создаётся замена…" : "Создаётся обложка…") : label}
        </button>
        {unsaved && (
          <span className="text-xs text-muted">{world ? "Сначала сохраните мир: обложка рисуется по сохранённому тексту." : "Сначала сохраните настройки стола: обложка рисуется по сохранённым данным."}</span>
        )}
        {art.inherited && !unsaved && (
          <span className="text-xs text-muted">Сейчас показана обложка мира. Своя заменит её только у этого стола.</span>
        )}
        {own && art.stale && !unsaved && (
          <span className="text-xs text-muted">Название или вводная изменились после создания обложки.</span>
        )}
      </div>

      {pending && (
        <p role="status" className="text-xs text-muted">
          Художник пишет картину… Прежняя обложка остаётся, пока не будет готова новая.
        </p>
      )}
      {message && (
        <p role="alert" className="text-xs text-bad">
          {message}
          {art.image_url ? " Прежняя обложка сохранена." : ""}
        </p>
      )}
    </section>
  );
}
