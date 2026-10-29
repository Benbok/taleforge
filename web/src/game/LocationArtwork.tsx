import { useEffect, useRef, useState } from "react";
import ArtworkViewer from "../components/ArtworkViewer";
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

function SavedImage({ url, name }: { url: string; name: string }) {
  const src = useAuthedImage(url);
  const [open, setOpen] = useState(false);
  return src ? (
    <>
      <button
        type="button"
        aria-label={`Открыть иллюстрацию локации «${name}»`}
        title="Рассмотреть иллюстрацию"
        className="group relative block w-full cursor-zoom-in overflow-hidden rounded-xl border border-line-soft/80 bg-surface shadow-md transition-all duration-200 hover:border-accent/60 hover:shadow-lg hover:shadow-accent/10 focus-visible:outline-2 focus-visible:outline-accent"
        onClick={() => setOpen(true)}
      >
        <img
          src={src}
          alt={`Иллюстрация локации «${name}»`}
          className="aspect-[3/2] w-full object-cover transition-transform duration-300 ease-out group-hover:scale-105"
        />
        <span
          className="pointer-events-none absolute bottom-2 right-2 flex items-center gap-1 rounded-md bg-black/80 px-2 py-0.5 font-mono text-[10px] font-medium text-white/90 backdrop-blur-xs opacity-0 transition-opacity duration-150 group-hover:opacity-100 shadow-xs"
          aria-hidden="true"
        >
          <span>⤢</span>
          <span>Увеличить</span>
        </span>
      </button>
      {open && (
        <ArtworkViewer
          src={src}
          name={name}
          label={`Локация «${name}»`}
          alt={`Иллюстрация локации «${name}»`}
          backdropTestId="location-artwork-backdrop"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  ) : (
    <div role="status" className="aspect-[3/2] content-center rounded-xl bg-surface-2 text-center text-xs text-muted">
      Загрузка иллюстрации…
    </div>
  );
}

/** The parent keys this component by location; late replies never replace another room's image. */
export default function LocationArtwork({ campaignId, locationId, name }: {
  campaignId: string; locationId: string; name: string;
}) {
  const endpoint = `/api/campaigns/${campaignId}/locations/${locationId}/artwork`;
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
          setLoadError("Не удалось проверить иллюстрацию места.");
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
      const data = await api<Artwork>(endpoint, {
        body: { request_key: requestKey.current, regenerate },
      });
      if (!active.current) return;
      setArtwork(data);
      requestKey.current = null;
    } catch (e) {
      if (!active.current) return;
      const pending = e instanceof ApiError && (e.data as { detail?: { code?: string } })?.detail?.code === "artwork_pending";
      if (!pending) {
        setError(e instanceof Error ? e.message : "Не удалось создать иллюстрацию.");
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

  if (!artwork || (!artwork.enabled && !artwork.image_url)) return null;

  const pending = busy || artwork.status === "pending";

  return (
    <div className="space-y-2" aria-label={`Иллюстрация локации ${name}`}>
      {artwork.image_url && <SavedImage key={artwork.image_url} url={artwork.image_url} name={name} />}

      {artwork.can_generate && !artwork.image_url && (
        <button
          type="button"
          disabled={pending}
          onClick={() => void generate(false)}
          className="btn-ghost w-full py-2 text-xs"
        >
          {pending ? "Создаётся иллюстрация…" : "Создать иллюстрацию"}
        </button>
      )}

      {artwork.can_generate && artwork.image_url && artwork.stale && (
        <button
          type="button"
          disabled={pending}
          onClick={() => void generate(true)}
          className="btn-ghost w-full py-2 text-xs text-muted hover:text-ink"
        >
          {pending ? "Обновляется иллюстрация…" : "Обновить иллюстрацию для нового описания"}
        </button>
      )}

      {pending && (
        <p role="status" className="text-center text-[11px] text-muted">
          Художник пишет картину… Можно продолжать игру.
        </p>
      )}

      {(error || artwork.error) && (
        <p role="alert" className="text-center text-[11px] text-bad">
          {error || artwork.error}
        </p>
      )}

      {loadError && !error && !artwork.error && (
        <div role="alert" className="text-center text-[11px] text-muted">
          <span>{loadError}</span>
          <button
            type="button"
            onClick={() => setRefresh((v) => v + 1)}
            className="ml-2 underline text-ink hover:text-accent"
          >
            Повторить проверку
          </button>
        </div>
      )}
    </div>
  );
}
