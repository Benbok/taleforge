import { Link } from "react-router-dom";
import { actionOf, STATUS_TEXT, statusOf, when } from "../lib/cards";
import type { CampaignCard } from "../lib/types";
import Avatar from "./Avatar";
import Recap from "./Recap";
import CampaignWorldLabel from "./CampaignWorldLabel";

const ROLE: Record<string, string> = { player: "Игрок", master: "Мастер" };

export default function CampaignCardView({
  c,
  featured = false,
}: {
  c: CampaignCard;
  featured?: boolean;
}) {
  const isLive = c.session_live;
  const status = statusOf(c);
  const action = actionOf(c);
  const canManage = Boolean(c.is_owner || c.my_role === "master");

  const heroDesc = c.hero
    ? `герой ${c.hero.name}${c.hero.level ? `, ${c.hero.level} ур.` : ""}`
    : c.my_role === "player"
      ? "героя ещё нет"
      : null;

  const roles = [
    c.my_role ? ROLE[c.my_role] : null,
    heroDesc,
    c.is_owner ? "владелец" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  let statusBadge = STATUS_TEXT[status] ?? status;
  if (status === "waiting" && c.waiting_players > 0) {
    const filled = c.party.filter((p) => p.occupant_type !== "empty").length;
    statusBadge = `Ждёт игроков · ${filled} / ${c.party.length}`;
  }

  const Heading = featured ? "h2" : "h3";
  const lastDate = when(c.last_session_at);

  return (
    <article
      className={`card relative flex min-w-0 flex-col overflow-hidden transition-colors duration-200 hover:border-accent/60 ${
        featured
          ? "border-accent/40 bg-surface shadow-sm"
          : "border-line bg-surface"
      }`}
    >
      {featured && (
        <svg
          aria-hidden="true"
          className="pointer-events-none absolute -right-12 top-2 hidden h-[340px] w-[340px] text-accent opacity-[0.14] lg:block"
          viewBox="0 0 360 360"
          fill="none"
          stroke="currentColor"
        >
          <circle cx="180" cy="180" r="145" />
          <circle cx="180" cy="180" r="125" strokeDasharray="2 7" />
          <circle cx="180" cy="180" r="92" />
          <path
            d="M180 17v326M17 180h326M65 65l230 230M65 295 295 65"
            strokeOpacity=".5"
          />
          <path d="m180 50 23 107 107 23-107 23-23 107-23-107-107-23 107-23Z" />
          <path
            d="m180 95 12 73 73 12-73 12-12 73-12-73-73-12 73-12Z"
            fill="currentColor"
            fillOpacity=".15"
          />
          <circle cx="180" cy="180" r="9" fill="currentColor" />
          <path
            d="m43 277 39-22 28 5 30-32 34 9 20-25 37 8 51-44 36 9"
            strokeDasharray="4 5"
          />
        </svg>
      )}
      {/* Мир и статус могут переноситься на узких экранах. */}
      <div
        className={`relative flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-2 px-5 py-4 ${featured ? "sm:px-8 sm:pt-7" : ""}`}
      >
        <CampaignWorldLabel campaign={c} />
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
            isLive
              ? "border-patina/40 bg-patina/10 text-patina-hi"
              : "border-line text-muted"
          }`}
        >
          {isLive && (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-patina" />
          )}
          {statusBadge}
        </span>
      </div>

      {/* Тело карточки */}
      <div
        className={`relative flex flex-1 flex-col gap-4 px-5 pb-5 ${featured ? "sm:px-8 sm:pb-7" : ""}`}
      >
        <div className={featured ? "lg:max-w-[75%]" : ""}>
          <Heading
            className={`break-words font-narration font-semibold leading-tight text-ink ${featured ? "text-3xl sm:text-[38px]" : "text-[23px]"}`}
          >
            {c.name}
          </Heading>
          <p className="mt-2 text-sm text-muted font-ui">
            {roles || "Наблюдатель"}
          </p>
        </div>

        {c.recap ? (
          <Recap
            text={c.recap}
            clamp={featured ? "line-clamp-3" : "line-clamp-2"}
            className={`font-narration leading-relaxed text-ink-2 ${featured ? "text-lg sm:text-xl lg:max-w-[75%]" : "text-sm"}`}
          />
        ) : (
          <p className="font-narration text-sm italic text-muted">
            {c.status === "ended"
              ? "Это приключение завершено. Его история осталась за столом."
              : isLive
                ? "Отряд уже за столом. Присоединяйтесь к истории."
                : "Новая история ждёт своего начала."}
          </p>
        )}

        {featured && lastDate && (
          <p className="text-xs text-muted">Последняя сессия · {lastDate}</p>
        )}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-line-soft">
          <div
            className="flex flex-wrap items-center gap-1.5"
            aria-label="Отряд"
          >
            {c.party.map((m) => (
              <Avatar
                key={m.seat_id}
                name={m.hero_name ?? m.user_name}
                role={m.role}
                occupant={m.occupant_type}
                presence={
                  m.occupant_type === "human"
                    ? m.online
                      ? "online"
                      : "offline"
                    : null
                }
                size={30}
              />
            ))}
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            {canManage && (
              <Link
                to={`/c/${c.id}/manage`}
                className="btn min-h-11 px-3.5 text-sm font-medium border-line text-muted hover:text-ink hover:border-accent bg-surface/80 transition-colors"
                title="Кабинет стола"
              >
                Кабинет
              </Link>
            )}

            <Link
              to={
                action.href === `/c/${c.id}/manage` ? `/c/${c.id}` : action.href
              }
              className={`btn min-h-11 flex-1 px-4 py-2 text-center text-sm font-medium sm:flex-none ${
                action.primary && isLive
                  ? "btn-primary"
                  : action.primary
                    ? "btn-outline-copper"
                    : "border-line text-ink hover:border-accent"
              }`}
            >
              {action.href === `/c/${c.id}/manage` ? "К столу" : action.label}
            </Link>
          </div>
        </div>
      </div>
    </article>
  );
}
