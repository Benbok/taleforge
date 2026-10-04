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

  let statusBadge = (STATUS_TEXT[status] ?? status).toUpperCase();
  if (status === "waiting" && c.waiting_players > 0) {
    const filled = c.party.filter((p) => p.occupant_type !== "empty").length;
    statusBadge = `ЖДЁТ ИГРОКОВ · ${filled} / ${c.party.length}`;
  }

  const isEcho =
    (c.world ?? "").toLowerCase().includes("эхо") ||
    (c.world ?? "").toLowerCase().includes("левиафан");
  const worldName = (c.world ?? "Базовые правила 5e").toUpperCase();

  return (
    <article
      className={`card flex flex-col overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg ${
        isLive ? "border-accent bg-[#17181c]" : "border-line bg-surface"
      }`}
    >
      {/* Шапка карточки 40px в моно */}
      <div
        className={`flex h-10 items-center justify-between px-5 font-mono text-[11px] tracking-[0.14em] border-b ${
          isLive ? "bg-[#1d1813] border-[#2e2620]" : "bg-surface-2 border-line"
        }`}
      >
        <span className={isEcho ? "text-copper-hi" : "text-muted"}>
          {worldName}
        </span>
        <span
          className={`flex items-center gap-1.5 font-medium ${
            isLive ? "text-patina-hi" : "text-muted"
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
          <h3 className="font-heading text-[28px] font-semibold leading-tight text-ink">
            {c.name}
          </h3>
          <p className="mt-1 text-xs text-muted font-ui">{roles || "Наблюдатель"}</p>
        </div>

        {c.recap ? (
          <Recap text={c.recap} className="font-narration text-[17px] italic leading-relaxed text-ink-2" />
        ) : (
          <p className="font-narration text-sm italic text-muted">
            {isLive ? "Сессия в процессе..." : "Ожидание начала вахты..."}
          </p>
        )}

        <div className="mt-auto flex items-center justify-between gap-3 pt-3 border-t border-line-soft">
          <div className="flex items-center gap-1.5" aria-label="Отряд">
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

          <Link
            to={action.href}
            className={`btn h-10 px-4 text-sm font-medium ${
              action.primary && isLive
                ? "btn-primary"
                : action.primary
                ? "btn-outline-copper"
                : "border-line text-ink hover:border-accent"
            }`}
          >
            {action.label}
          </Link>
        </div>
      </div>
    </article>
  );
}
