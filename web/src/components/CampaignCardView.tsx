import { Link } from "react-router-dom";
import { actionOf, STATUS_TEXT, statusOf } from "../lib/cards";
import type { CampaignCard } from "../lib/types";
import Avatar from "./Avatar";
import Recap from "./Recap";

const ROLE: Record<string, string> = { player: "Игрок", master: "Мастер" };

export default function CampaignCardView({ c }: { c: CampaignCard }) {
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

  const isEcho =
    (c.world ?? "").toLowerCase().includes("эхо") ||
    (c.world ?? "").toLowerCase().includes("левиафан");
  const worldName = c.world ?? "Базовые правила 5e";

  return (
    <article
      className={`card flex flex-col overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg ${
        isLive ? "border-accent bg-surface shadow-sm" : "border-line bg-surface"
      }`}
    >
      {/* Мир и статус могут переноситься на узких экранах. */}
      <div
        className={`flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-2 px-5 py-3 text-sm border-b ${
          isLive ? "bg-accent/10 border-accent/30" : "bg-surface-2 border-line"
        }`}
      >
        <span className={`min-w-0 break-words ${isEcho ? "text-copper-hi" : "text-muted"}`}>
          {worldName}
        </span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
            isLive ? "border-patina/40 bg-patina/10 text-patina-hi" : "border-line text-muted"
          }`}
        >
          {isLive && (
            <span className="inline-block h-2 w-2 rounded-full bg-patina animate-pulse" />
          )}
          {statusBadge}
        </span>
      </div>

      {/* Тело карточки */}
      <div className="flex flex-1 flex-col gap-3 p-5">
        <div>
          <h3 className="break-words font-heading text-[30px] font-semibold leading-tight text-ink">
            {c.name}
          </h3>
          <p className="mt-2 text-sm text-muted font-ui">{roles || "Наблюдатель"}</p>
        </div>

        {c.recap ? (
          <Recap text={c.recap} className="font-narration text-[20px] leading-relaxed text-ink-2" />
        ) : (
          <p className="font-narration text-sm italic text-muted">
            {isLive ? "Сессия в процессе..." : "Ожидание начала вахты..."}
          </p>
        )}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-line-soft">
          <div className="flex flex-wrap items-center gap-1.5" aria-label="Отряд">
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
              to={action.href === `/c/${c.id}/manage` ? `/c/${c.id}` : action.href}
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
