import type { MouseEvent } from "react";
import Avatar from "../components/Avatar";
import type { EntityType, HeroPublic, SceneEntity } from "../lib/types";
import { useGame } from "../stores/game";
import DeathSaves from "./DeathSaves";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";

function sceneType(e: SceneEntity): EntityType {
  if (e.kind === "item") return "item";
  return e.attitude === "hostile" ? "creature" : "npc"; // так же делит сервер (core/inspect.entity_type)
}

function Hp({ h }: { h: HeroPublic }) {
  if (h.hp == null || !h.hp_max) return null;
  const pct = Math.max(0, Math.min(100, (h.hp / h.hp_max) * 100));
  const color = pct > 50 ? "var(--color-ok)" : pct > 25 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <span className="mt-1 block" title={`Хиты ${h.hp} из ${h.hp_max}`}>
      <span className="block h-1.5 w-full overflow-hidden rounded-full bg-raised">
        <span className="block h-full transition-[width] duration-500" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span className="text-xs text-muted">
        {h.hp} / {h.hp_max}
      </span>
    </span>
  );
}

/** Отряд: места за столом, присутствие, у героев — хиты (их видят все участники, как за столом). */
export function PartyPanel() {
  const { seats, heroes, turn, snapshot } = useGame();
  const open = useInspector((s) => s.open);
  const heroBySeat = new Map<string, HeroPublic>();
  for (const h of Object.values(heroes)) if (h.seat_id && (!heroBySeat.has(h.seat_id) || !h.dead)) heroBySeat.set(h.seat_id, h);
  const sorted = seats
    .slice()
    .sort((a, b) => (a.role === "master" ? -1 : b.role === "master" ? 1 : a.position - b.position));

  return (
    <section className="card p-4" aria-label="Отряд">
      <h2 className="mb-3 text-base font-semibold">Отряд</h2>
      <ul className="flex flex-col gap-3">
        {sorted.map((s) => {
          const h = heroBySeat.get(s.id);
          const acting = !!turn && turn.seat_id === s.id;
          const mine = s.id === snapshot?.me.seat_id;
          const title =
            s.role === "master"
              ? s.occupant_type === "agent"
                ? "ИИ-мастер"
                : `Мастер: ${s.user_name ?? "—"}`
              : (h?.name ?? (s.occupant_type === "empty" ? "Свободное место" : "Герой не готов"));
          return (
            <li key={s.id} className={`flex items-start gap-3 rounded-md ${acting ? "bg-raised p-1.5 ring-1 ring-accent" : ""}`}>
              <Avatar
                name={h?.name ?? s.user_name}
                role={s.role}
                occupant={s.occupant_type}
                presence={s.occupant_type === "human" ? (s.presence ?? "offline") : null}
              />
              <span className="min-w-0 flex-1">
                {h ? (
                  <button
                    className="block max-w-full truncate text-left hover:underline"
                    onClick={(e: MouseEvent<HTMLButtonElement>) => open(h.id, h.name, e.currentTarget)}
                  >
                    {title}
                    {mine && <span className="text-muted"> (вы)</span>}
                    {h.dead && <span className="text-bad"> · пал</span>}
                  </button>
                ) : (
                  <span className="block truncate">{title}</span>
                )}
                {s.role === "player" && s.user_name && (
                  <span className="block text-xs text-muted">
                    {s.user_name}
                    {h ? ` · ур. ${h.level}` : ""}
                    {acting ? " · ходит" : ""}
                  </span>
                )}
                {h && !h.dead && <Hp h={h} />}
                {h && !h.dead && h.hp === 0 && h.death_saves && <DeathSaves saves={h.death_saves} label="Без сознания:" />}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Сцена: где отряд и кто рядом. Только то, что видно всем; подробности — по клику, в карточке знаний. */
export function ScenePanel() {
  const scene = useGame((s) => s.scene);
  const open = useInspector((s) => s.open);
  if (!scene) return null;
  return (
    <section className="card p-4" aria-label="Сцена">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Сцена</h2>
        {scene.mode === "combat" && (
          <span className="rounded-full border border-bad px-2 py-0.5 text-xs text-bad">Бой · раунд {scene.round || 1}</span>
        )}
      </div>
      {scene.location ? (
        <button
          className="mb-3 block text-left"
          style={{ color: TYPE_COLOR.location }}
          onClick={(e) => open(scene.location!.id, scene.location!.name, e.currentTarget)}
        >
          {TYPE_ICON.location} {scene.location.name}
        </button>
      ) : (
        <p className="mb-3 text-muted">Место ещё не названо.</p>
      )}
      {scene.entities.length === 0 ? (
        <p className="text-xs text-muted">Рядом никого.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {scene.entities.map((e) => {
            const t = sceneType(e);
            const acting = scene.turn?.actor_id === e.id;
            return (
              <li key={e.id} className="flex items-baseline justify-between gap-2">
                <button
                  className={`truncate text-left underline decoration-dotted underline-offset-4 ${acting ? "font-semibold" : ""}`}
                  style={{ color: TYPE_COLOR[t] }}
                  onClick={(ev) => open(e.id, e.name, ev.currentTarget)}
                >
                  {TYPE_ICON[t]} {e.name}
                </button>
                <span className="shrink-0 text-xs text-muted">
                  {[e.condition, e.zone, acting ? "ходит" : null].filter(Boolean).join(" · ")}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
