import { useState } from "react";
import { useMenuMusicPreferences } from "./menuMusicPreferences";
import { useSound } from "../game/sound";

/** Компактная кнопка темы в шапке кабинета. */
export default function MenuMusicControl() {
  const sound = useSound();
  const prefs = useMenuMusicPreferences((s) => s.prefs);
  const update = useMenuMusicPreferences((s) => s.update);
  const [busy, setBusy] = useState(false);

  if (sound.audioSurface !== "menu" || !sound.menuTheme) return null;
  const retryable = sound.menuStatus === "error";
  const locked = !sound.unlocked || sound.menuStatus === "locked" || retryable;
  const loading = busy || sound.menuStatus === "loading";
  const label = locked ? "Включить музыку" : prefs.enabled ? "Выключить музыку" : "Включить музыку";

  async function activate() {
    if (!locked) {
      update({ enabled: !prefs.enabled });
      return;
    }
    setBusy(true);
    const attempt = sound.unlock();
    try {
      await attempt;
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className="btn btn-outline-copper h-8 shrink-0 px-2.5 text-xs"
      onClick={() => void activate()}
      disabled={loading}
      aria-busy={loading}
      aria-label={label}
      title={sound.menuError ?? sound.menuTheme.title}
    >
      {loading ? "…" : `♪ ${label}`}
    </button>
  );
}
