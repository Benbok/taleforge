import { useMenuMusicPreferences } from "../audio/menuMusicPreferences";
import { useSound } from "../game/sound";

/** Настройки темы приложения, сохранённые в аккаунте отдельно от звука сцены. */
export default function AudioSettingsSection() {
  const prefs = useMenuMusicPreferences((s) => s.prefs);
  const saveState = useMenuMusicPreferences((s) => s.saveState);
  const update = useMenuMusicPreferences((s) => s.update);
  const retry = useMenuMusicPreferences((s) => s.retry);
  const sound = useSound();
  const title = sound.menuTheme?.title ?? "Edge of the World";

  return (
    <section className="card border border-line bg-surface p-5 sm:p-6" aria-label="Звук приложения">
      <div className="flex flex-col gap-1">
        <h3 className="font-heading text-base font-bold text-ink">Звук приложения</h3>
        <p className="text-xs text-muted">Фоновая музыка кабинета не меняет громкость звука в игре.</p>
      </div>
      <div className="mt-4 flex flex-col gap-4">
        <label className="flex items-center justify-between gap-3 text-sm text-ink">
          <span>Музыка главного меню</span>
          <input
            type="checkbox"
            checked={prefs.enabled}
            onChange={(e) => update({ enabled: e.target.checked })}
            aria-label="Музыка главного меню"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-xs text-ink">
          <span className="flex items-center justify-between gap-2">
            <span>Громкость музыки меню</span>
            <span className="font-mono text-muted">{Math.round(prefs.volume * 100)}%</span>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round(prefs.volume * 100)}
            onChange={(e) => update({ volume: Number(e.target.value) / 100 })}
            aria-label="Громкость музыки меню"
          />
          <span className="text-[11px] text-muted">Трек: {title}</span>
        </label>
        {saveState === "error" && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-bad" role="alert">
            <span>Не удалось сохранить настройки музыки</span>
            <button type="button" className="btn px-2 py-1 text-xs" onClick={retry}>Повторить</button>
          </div>
        )}
      </div>
    </section>
  );
}
