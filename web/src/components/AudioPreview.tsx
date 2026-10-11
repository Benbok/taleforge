import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";

/** Authenticated preview; independent from the game's broadcast audio state. */
export default function AudioPreview({ path, title }: { path: string; title: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);
  useEffect(() => {
    setUrl(null);
    setError(null);
    setLoading(false);
    return () => {
      abort.current?.abort();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
  }, [path]);

  async function load() {
    abort.current?.abort();
    const request = new AbortController();
    abort.current = request;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(path, {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` }, signal: request.signal,
      });
      if (!response.ok) throw new Error("Не удалось загрузить звук");
      const blob = await response.blob();
      if (request.signal.aborted) return;
      objectUrl.current = URL.createObjectURL(blob);
      setUrl(objectUrl.current);
    } catch (e) {
      if (!request.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {url ? <audio controls src={url} aria-label={`Прослушать ${title}`} className="h-9 max-w-full" /> : (
        <button type="button" className="btn px-3 py-1 text-xs" disabled={loading} onClick={() => void load()}>
          {loading ? "Загрузка…" : "Прослушать"}
        </button>
      )}
      {error && <span role="alert" className="text-xs text-bad">{error}</span>}
    </div>
  );
}
