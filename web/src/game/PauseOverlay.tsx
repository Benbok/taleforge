import { useState } from "react";
import { useGame } from "../stores/game";

/** Между сессиями экран затемняется: «Пауза» и итог сессии. Итог приходит, когда мастер допишет сводку.
 *  Затемнение можно убрать, чтобы перечитать чат. */
export default function PauseOverlay({ controls }: { controls?: React.ReactNode }) {
  const status = useGame((s) => s.snapshot?.campaign.status);
  const live = useGame((s) => !!s.snapshot?.session);
  const summary = useGame((s) => s.summary);
  // итог и эпилог пишет только ИИ-мастер; у живого мастера их не ждём
  const aiMaster = useGame((s) => s.seats.some((x) => x.role === "master" && x.occupant_type === "agent"));
  const [hidden, setHidden] = useState<string | null>(null);
  const shown = !live && (status === "paused" || status === "ended");
  if (!shown || hidden === status) return null;
  const ended = status === "ended";

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]" role="dialog" aria-label={ended ? "Кампания завершена" : "Пауза"}>
      <div className="card tf-pop flex max-h-full w-full max-w-lg flex-col gap-3 overflow-y-auto p-5">
        <h2 className="font-heading text-xl">{ended ? "Кампания завершена" : "Пауза"}</h2>
        {summary?.recap ? (
          <>
            <p className="text-xs uppercase tracking-wide text-muted">Итог сессии</p>
            <p className="font-narration leading-relaxed">{summary.recap}</p>
            {summary.events.length > 0 && (
              <ul className="list-disc pl-5 text-sm text-muted">
                {summary.events.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
            {!ended && summary.quests.length > 0 && (
              <>
                <p className="text-xs uppercase tracking-wide text-muted">Что впереди</p>
                <ul className="list-disc pl-5 text-sm">
                  {summary.quests.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <p className="text-muted" role="status">
            {!aiMaster
              ? ended
                ? "Играть в этой кампании больше нельзя, чат остаётся для чтения."
                : "Сессия остановлена. Продолжить может владелец кампании."
              : ended
                ? "Мастер пишет эпилог…"
                : "Мастер подводит итог сессии…"}
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {controls}
          <button className="btn ml-auto" onClick={() => setHidden(status ?? null)}>
            Перечитать чат
          </button>
        </div>
      </div>
    </div>
  );
}
