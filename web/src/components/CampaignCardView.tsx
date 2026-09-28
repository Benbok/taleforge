import { Link } from "react-router-dom";
import { actionOf, STATUS_TEXT, statusOf, when } from "../lib/cards";
import type { CampaignCard } from "../lib/types";
import Avatar from "./Avatar";

const ROLE: Record<string, string> = { player: "игрок", master: "мастер" };

export default function CampaignCardView({ c }: { c: CampaignCard }) {
  const status = statusOf(c);
  const action = actionOf(c);
  const roles = [c.my_role ? ROLE[c.my_role] : null, c.is_owner ? "владелец" : null].filter(Boolean).join(", ");
  const last = when(c.last_session_at);
  return (
    <article className="card flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold">{c.name}</h3>
          <p className="text-muted">{c.world ?? "Базовые правила"}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
            status === "live" ? "bg-accent text-on-accent" : "border border-line text-muted"
          }`}
        >
          {STATUS_TEXT[status]}
        </span>
      </div>
      <p className="text-muted">
        {roles && <>Моя роль: {roles}. </>}
        {c.hero && (
          <>
            Герой: <span className="text-ink">{c.hero.name}</span>
            {c.hero.level ? `, ${c.hero.level} ур.` : ""}
          </>
        )}
      </p>
      <div className="flex flex-wrap gap-1.5" aria-label="Отряд">
        {c.party.map((m) => (
          <Avatar
            key={m.seat_id}
            name={m.hero_name ?? m.user_name}
            role={m.role}
            occupant={m.occupant_type}
            presence={m.occupant_type === "human" ? (m.online ? "online" : "offline") : null}
          />
        ))}
      </div>
      {c.recap && (
        <p className="font-narration text-sm leading-relaxed">
          <span className="text-muted">Ранее в кампании… </span>
          {c.recap}
        </p>
      )}
      <div className="mt-auto flex items-center justify-between gap-2">
        <span className="text-xs text-muted">{last ? `Прошлая сессия: ${last}` : ""}</span>
        <Link to={action.href} reloadDocument={action.href.startsWith("/legacy")} className={`btn ${action.primary ? "btn-primary" : ""}`}>
          {action.label}
        </Link>
      </div>
    </article>
  );
}
