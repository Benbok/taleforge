import { useEffect, useState } from "react";
import { getToken } from "./api";

/** Картинка по защищённой ссылке: тег <img> не шлёт токен, поэтому файл берётся запросом и показывается как blob. */
export function useAuthedImage(url: string): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (!alive || !b) return;
        made = URL.createObjectURL(b);
        setSrc(made);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  return src;
}
