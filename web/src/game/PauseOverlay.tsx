import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Room } from "../lib/campaign";
import type { HeroPublic } from "../lib/types";
import { useGame } from "../stores/game";
import BondsForm from "./BondsForm";

/** Между сессиями экран затемняется. До первой сессии — лобби: афиша, кто готов, вопросы о связях героя.
 *  На паузе — «Ранее в кампании…»: итог сессии, когда мастер допишет сводку. После конца — эпилог.
 *  Затемнение можно убрать, чтобы перечитать чат. */
export default function PauseOverlay({ campaignId, controls }: { campaignId: string; controls?: ReactNode }) {
  const status = useGame((s) => s.snapshot?.campaign.status);
  const intro = useGame((s) => s.snapshot?.campaign.public_intro);
  const live = useGame((s) => !!s.snapshot?.session);
  const summary = useGame((s) => s.summary);
  const role = useGame((s) => s.snapshot?.me.role);
  // итог и эпилог пишет только ИИ-мастер; у живого мастера их не ждём
  const aiMaster = useGame((s) => s.seats.some((x) => x.role === "master" && x.occupant_type === "agent"));
  const room = useQuery({ queryKey: ["room", campaignId], queryFn: () => api<Room>(`/api/campaigns/${campaignId}`), enabled: !live });
  const [hidden, setHidden] = useState<string | null>(null);
  const shown = !live && (status === "lobby" || status === "paused" || status === "ended");
  if (!shown || hidden === status) return null;
  const ended = status === "ended";
  const lobby = status === "lobby";
  const poster = room.data?.settings.poster;
  const manage = room.data?.is_owner || role === "master";

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]" role="dialog" aria-label={ended ? "Кампания завершена" : lobby ? "Лобби" : "Пауза"}>
      <div className="card tf-pop flex max-h-full w-full max-w-xl flex-col gap-4 overflow-y-auto p-5">
        <div>
          <h2 className="font-heading text-xl">{ended ? "Кампания завершена" : lobby ? (poster?.title ?? "Скоро начнём") : "Пауза"}</h2>
          {lobby && poster?.tagline && <p className="font-narration italic text-muted">{poster.tagline}</p>}
        </div>
        {lobby && intro && <p className="whitespace-pre-line font-narration leading-relaxed">{intro}</p>}

        {!lobby &&
          (summary?.recap ? (
            <section className="flex flex-col gap-2">
              <p className="text-xs uppercase tracking-wide text-muted">{ended ? "Итог" : "Ранее в кампании…"}</p>
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
            </section>
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
          ))}

        {!ended && <Readiness campaignId={campaignId} />}

        <div className="mt-1 flex flex-wrap items-center gap-2">
          {controls}
          {manage && !ended && (
            <Link className="btn" to={`/c/${campaignId}/manage`}>
              Кабинет
            </Link>
          )}
          <button className="btn ml-auto" onClick={() => setHidden(status ?? null)}>
            Перечитать чат
          </button>
        </div>
      </div>
    </div>
  );
}

/** Кто готов к игре: герой в игре и игрок в сети. Свой герой — с вопросами о связях, чужие — с открытыми ответами. */
function Readiness({ campaignId }: { campaignId: string }) {
  const seats = useGame((s) => s.seats);
  const heroes = useGame((s) => s.heroes);
  const mySeat = useGame((s) => s.snapshot?.me.seat_id);
  const [openBonds, setOpenBonds] = useState(false);
  const players = seats.filter((s) => s.role === "player" && s.occupant_type !== "empty").sort((a, b) => a.position - b.position);
  if (!players.length) return <p className="text-sm text-muted">За столом пока нет игроков. Владелец может позвать их ссылкой-приглашением.</p>;
  const heroOf = (seatId: string): HeroPublic | undefined =>
    Object.values(heroes).find((h) => h.seat_id === seatId && !h.dead && h.status !== "dead");
  const state = (h: HeroPublic | undefined, online: boolean) =>
    !h ? ["собирает героя", "text-muted"] : h.status === "submitted" ? ["герой на проверке", "text-muted"] : online ? ["готов", "text-ok"] : ["не в сети", "text-muted"];
  const ready = players.filter((s) => {
    const h = heroOf(s.id);
    return h && h.status !== "submitted" && (s.occupant_type === "agent" || s.presence === "online");
  }).length;
  const mine = mySeat ? heroOf(mySeat) : undefined;

  return (
    <section className="flex flex-col gap-2">
      <p className="text-xs uppercase tracking-wide text-muted">
        Отряд · готовы {ready} из {players.length}
      </p>
      <ul className="flex flex-col gap-2">
        {players.map((s) => {
          const h = heroOf(s.id);
          const [text, tone] = state(h, s.occupant_type === "agent" || s.presence === "online");
          return (
            <li key={s.id} className="text-sm">
              <span className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  {h?.name ?? s.user_name ?? "ИИ-игрок"}
                  {h && s.user_name && <span className="text-muted"> · {s.user_name}</span>}
                  {s.id === mySeat && <span className="text-muted"> (вы)</span>}
                </span>
                {s.id === mySeat && (!h || h.status === "submitted") ? (
                  <Link className="text-accent" to={`/c/${campaignId}/hero`}>
                    {h ? "герой на проверке →" : "собрать героя →"}
                  </Link>
                ) : (
                  <span className={tone}>{text}</span>
                )}
              </span>
              {s.id !== mySeat && !!h?.bonds?.length && (
                <ul className="mt-1 border-l border-line pl-3 text-xs text-muted">
                  {h.bonds.map((b, i) => (
                    <li key={i}>
                      {b.question} <span className="text-ink">{b.answer}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      {mine && mine.status !== "submitted" && (
        <div className="rounded-md border border-line p-3">
          <button className="w-full text-left text-sm font-semibold" aria-expanded={openBonds} onClick={() => setOpenBonds((x) => !x)}>
            {openBonds ? "▾" : "▸"} Связи героя: вопросы мастера
          </button>
          {openBonds && (
            <div className="mt-3">
              <BondsForm campaignId={campaignId} heroId={mine.id} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
