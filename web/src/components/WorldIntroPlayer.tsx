import { useEffect, useRef, useState } from "react";

export interface WorldIntroPlayerProps {
  audioUrl?: string;
  title?: string;
  subtitle?: string;
  compact?: boolean;
  className?: string;
}

const DEFAULT_TRANSCRIPT = `Триста лет назад они рухнули с небес. Не боги и не чудовища… Колоссальные живые корабли, чьих строителей никто не видел. Наш старый мир сгорел в их падении. Новый — вырос прямо на их остывающих костях.

Людей спасло мародёрство. Мы рубим плоть туш шахтными пилами, куём доспехи из хитина санитаров, а паровые котлы городов кормим ликвором — едким топливом из их вен.

Здесь больше нет молитв — боги умерли, если вообще существовали. Всякая магия этой эпохи пахнет озоном и медью. И за каждую искру силы плоть расплачивается Переменой, медленно превращая человека в чудовище.

А в темноте за чертой растёт Скверна. Из утроб погибших титанов лезет Рой, жаждущий вернуть украденное. А в запечатанных рубках всё ещё спят древние Кормчие… и они начинают видеть сны.

Проверь фильтр маски! Затяни ремни на инъекторе! Тут ты не найдешь ничего, что тебя спасет и избавит от страданий! Приготовься сражаться за свою жизнь.....`;

function formatTime(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function WorldIntroPlayer({
  audioUrl = "/audio/echo-leviathans-intro.mp3",
  title = "«Хроника черты»",
  subtitle = "Аудиовводная вселенной «Эхо Левиафанов»",
  compact = false,
  className = "",
}: WorldIntroPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(78); // ~77.6s по умолчанию
  const [showTranscript, setShowTranscript] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onLoadedMetadata = () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration);
      }
    };
    const onEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("ended", onEnded);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.removeEventListener("ended", onEnded);
    };
  }, []);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      audio.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }
  };

  const onSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value);
    setCurrentTime(val);
    if (audioRef.current) {
      audioRef.current.currentTime = val;
    }
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      className={`rounded-[10px] border border-accent/40 bg-surface/90 shadow-md backdrop-blur-sm transition-all overflow-hidden ${
        compact ? "p-3" : "p-4 sm:p-5"
      } ${className}`}
    >
      <audio ref={audioRef} src={audioUrl} preload="metadata" />

      {/* Верхняя строка плеера */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* Кнопка Play/Pause */}
          <button
            type="button"
            onClick={togglePlay}
            aria-label={isPlaying ? "Приостановить воспроизведение" : "Слушать вводную"}
            className="group relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-accent/60 bg-accent/15 text-accent shadow-sm transition hover:scale-105 hover:border-accent hover:bg-accent/25 active:scale-95"
          >
            {isPlaying ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16" rx="1" />
                <rect x="14" y="4" width="4" height="16" rx="1" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" className="translate-x-0.5">
                <path d="M5 3.879v16.242a1 1 0 0 0 1.545.841l13.116-8.121a1 1 0 0 0 0-1.682L6.545 3.038A1 1 0 0 0 5 3.879Z" />
              </svg>
            )}
            {isPlaying && (
              <span className="absolute -inset-1 rounded-full border border-accent/40 animate-ping pointer-events-none opacity-40" />
            )}
          </button>

          {/* Название и информация */}
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-heading font-bold text-sm sm:text-base text-ink truncate">{title}</span>
              <span className="rounded-full border border-patina/40 bg-patina/10 px-2 py-0.2 font-mono text-[10px] text-patina-hi uppercase tracking-wider shrink-0">
                Эхо Левиафанов
              </span>
            </div>
            <span className="text-xs text-muted truncate">{subtitle}</span>
          </div>
        </div>

        {/* Время и кнопка разворота текста */}
        <div className="flex items-center justify-between sm:justify-end gap-3 font-mono text-xs text-muted shrink-0">
          {/* Индикатор звуковой волны при игре */}
          {isPlaying && (
            <div className="flex items-end gap-0.5 h-3.5 px-1" title="Воспроизведение">
              <span className="w-1 bg-accent rounded-full animate-[pulse_0.6s_ease-in-out_infinite]" style={{ height: "60%" }} />
              <span className="w-1 bg-accent rounded-full animate-[pulse_0.4s_ease-in-out_infinite_0.1s]" style={{ height: "100%" }} />
              <span className="w-1 bg-accent rounded-full animate-[pulse_0.8s_ease-in-out_infinite_0.2s]" style={{ height: "40%" }} />
              <span className="w-1 bg-accent rounded-full animate-[pulse_0.5s_ease-in-out_infinite_0.3s]" style={{ height: "80%" }} />
            </div>
          )}

          <span className="text-ink-2 font-mono">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>

          <button
            type="button"
            onClick={() => setShowTranscript((v) => !v)}
            className="flex items-center gap-1 rounded border border-line bg-raised px-2 py-1 text-[11px] text-ink-2 hover:border-accent/40 hover:text-accent transition"
          >
            <span>{showTranscript ? "Скрыть текст" : "Текст"}</span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={`transition-transform duration-200 ${showTranscript ? "rotate-180" : ""}`}
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
        </div>
      </div>

      {/* Полоса прогресса */}
      <div className="mt-3 relative flex items-center">
        <input
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={currentTime}
          onChange={onSeek}
          aria-label="Перемотка аудиовводной"
          className="w-full h-1.5 rounded-lg appearance-none cursor-pointer bg-raised accent-[var(--tf-accent)] focus:outline-none"
          style={{
            background: `linear-gradient(to right, var(--tf-accent, #b87333) ${progressPercent}%, rgba(100,100,100,0.2) ${progressPercent}%)`,
          }}
        />
      </div>

      {/* Выпадающий текст озвучки */}
      {showTranscript && (
        <div className="mt-4 pt-3 border-t border-line/60 flex flex-col gap-2.5 animate-fadeIn">
          <div className="flex items-center justify-between text-[11px] font-mono text-muted uppercase tracking-wider">
            <span>Расшифровка хроники:</span>
            <span>Диктор · 1 мин 17 сек</span>
          </div>
          <div className="font-narration text-sm sm:text-base leading-relaxed text-ink-2 whitespace-pre-line bg-raised/30 p-3 sm:p-4 rounded-[8px] border border-line/40 italic">
            {DEFAULT_TRANSCRIPT}
          </div>
        </div>
      )}
    </div>
  );
}
