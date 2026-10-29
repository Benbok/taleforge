import { useCallback, useEffect, useState } from "react";
import { getToken } from "./api";

/** Картинка по защищённой ссылке: тег <img> не шлёт токен, поэтому файл берётся запросом и показывается как blob. */
export function useAuthedImage(url: string): string | null {
  return useAuthedImageResource(url).src;
}

/** Download errors can be retried without triggering a new image generation. */
export function useAuthedImageResource(url: string) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ url: string; src: string | null; error: boolean }>({ url, src: null, error: false });
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    const controller = new AbortController();
    setState({ url, src: null, error: false });
    fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ""}` }, signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error('Image unavailable'); return r.blob(); })
      .then((b) => {
        if (!alive) return;
        made = URL.createObjectURL(b);
        setState({ url, src: made, error: false });
      })
      .catch(() => { if (alive) setState({ url, src: null, error: true }); });
    return () => {
      alive = false;
      controller.abort();
      if (made) URL.revokeObjectURL(made);
    };
  }, [url, attempt]);
  return { src: state.url === url ? state.src : null, error: state.url === url && state.error, retry };
}
