import { useEffect, useRef, useState } from "react";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { CHANNEL_LABELS, CHANNELS, useSound } from "./sound";

/** Динамик в шапке игры: включить звук (браузер требует нажатия), громкость музыки и эффектов, что сейчас звучит.
 *  Виден, только когда владелец включил звук в кампании. */
export default function SoundControl() {
  const s = useSound();
  const audio = useGame((g) => g.audio);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!audio?.enabled) return null;
  const music = audio.music;

  async function unlock() {
    setBusy(true);
    try {
      await s.unlock();
      toast.ok(music ? `Звук включён: ${music.title}` : "Звук включён: музыка начнётся со следующего хода");
    } catch (e) {
      toast.error(`Звук не включился: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!s.unlocked) {
    return (
      <button
        type="button"
        className="btn btn-outline-copper h-8 shrink-0 px-2.5 text-xs"
        onClick={unlock}
        disabled={busy}
        aria-busy={busy}
        title="Музыка сцены и эффекты. Браузер играет их только после нажатия."
      >
        {busy ? "…" : "♪ Включить звук"}
      </button>
    );
  }

  const muted = s.prefs.muted;
  return (
    <div className="relative shrink-0" ref={box}>
      <button
        type="button"
        className="btn h-8 max-w-[14rem] gap-1.5 px-2.5 text-xs"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Звук сцены"
        title={music ? `Звучит: ${music.title}` : "Звук сцены"}
      >
        <span aria-hidden="true">{muted ? "🔇" : "♪"}</span>
        <span className="hidden truncate sm:inline">{muted ? "звук выключен" : (music?.title ?? "тишина")}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-40 flex w-72 flex-col gap-3 rounded-xl border border-line bg-surface p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <span className="font-heading text-sm text-ink">Звук сцены</span>
            <button
              type="button"
              className="btn px-2 py-0.5 text-xs"
              onClick={() => {
                s.setPrefs({ muted: !muted });
                toast.info(muted ? "Звук включён" : "Звук выключен у вас; у остальных он играет");
              }}
            >
              {muted ? "Включить" : "Выключить"}
            </button>
          </div>
          <Slider label="Общая" value={s.prefs.master} onChange={(v) => s.setPrefs({ master: v })} />
          {CHANNELS.map((ch) => (
            <Slider
              key={ch}
              label={CHANNEL_LABELS[ch]}
              note={ch === "music" ? (music?.title ?? "тишина") : undefined}
              value={s.prefs[ch]}
              onChange={(v) => s.setPrefs({ [ch]: v })}
            />
          ))}
          {s.error && <p className="text-xs text-bad">{s.error}</p>}
          <p className="text-[11px] text-muted">Громкость хранится в этом браузере и не меняет звук у других игроков.</p>
        </div>
      )}
    </div>
  );
}

function Slider({
  label,
  note,
  value,
  onChange,
}: {
  label: string;
  note?: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="flex justify-between gap-2">
        <span className="text-ink">{label}</span>
        {note && <span className="truncate text-muted">{note}</span>}
      </span>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`Громкость: ${label}`}
      />
    </label>
  );
}
