import type { MouseEvent } from "react";
import Avatar from "../components/Avatar";
import type { EntityType, HeroPublic, SceneEntity, SeatState } from "../lib/types";
import { useGame } from "../stores/game";
import DeathSaves from "./DeathSaves";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";

function sceneType(e: SceneEntity): EntityType {
  if (e.kind === "item") return "item";
  return e.attitude === "hostile" ? "creature" : "npc";
}

function Hp({ h }: { h: HeroPublic }) {
  if (h.hp == null || !h.hp_max) return null;
  const pct = Math.max(0, Math.min(100, (h.hp / h.hp_max) * 100));
  const color = pct > 50 ? "var(--tf-patina)" : pct > 25 ? "var(--color-warn)" : "var(--tf-ember)";

  return (
    <div className="mt-1.5 flex flex-col gap-0.5" title={`Хиты ${h.hp} из ${h.hp_max}`}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised">
        <div
          className="h-full transition-[width] duration-500 rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="flex justify-between font-mono text-[10px] text-muted tabular-nums">
        <span>HP</span>
        <span>
          {h.hp} / {h.hp_max}
        </span>
      </div>
    </div>
  );
}

/** Отряд: места за столом, присутствие, у героев — хиты (их видят все участники, как за столом). */
export function PartyPanel() {
  const { seats, heroes, turn, snapshot } = useGame();
  const open = useInspector((s) => s.open);
  const heroBySeat = new Map<string, HeroPublic>();
  for (const h of Object.values(heroes)) {
    if (h.seat_id && (!heroBySeat.has(h.seat_id) || !h.dead)) heroBySeat.set(h.seat_id, h);
  }
  const sorted = seats
    .slice()
    .sort((a, b) => (a.role === "master" ? -1 : b.role === "master" ? 1 : a.position - b.position));

  return (
    <section className="card p-4 sm:p-5 border border-line bg-surface flex flex-col gap-3" aria-label="Отряд">
      <div className="flex items-center justify-between border-b border-line pb-2.5">
        <h2 className="font-heading text-lg font-bold text-ink">Отряд экспедиции</h2>
        <span className="font-mono text-xs text-muted">
          {sorted.filter((s) => s.role === "player").length} мест
        </span>
      </div>

      <ul className="flex flex-col gap-2.5">
        {sorted.map((s) => {
          const h = heroBySeat.get(s.id);
          const acting = !!turn && turn.seat_id === s.id;
          const mine = s.id === snapshot?.me.seat_id;
          const title =
            s.role === "master"
              ? s.occupant_type === "agent"
                ? s.stand_in?.ai
                  ? `ИИ-мастер вместо ${s.user_name ?? "мастера"}`
                  : "ИИ-мастер"
                : `Мастер: ${s.user_name ?? "—"}`
              : (h?.name ?? (s.occupant_type === "empty" ? "Свободное место" : "Герой не готов"));

          return (
            <li
              key={s.id}
              className={`flex items-start gap-3 rounded-[10px] p-2 transition ${
                acting
                  ? "bg-accent/10 border border-accent shadow-[0_0_12px_rgba(201,138,75,0.15)] ring-1 ring-accent/40"
                  : "border border-line/60 bg-raised/40 hover:border-line"
              }`}
            >
              <Avatar
                name={h?.name ?? s.user_name}
                role={s.role}
                occupant={s.occupant_type}
                presence={s.occupant_type === "human" ? (s.presence ?? "offline") : null}
              />

              <span className="min-w-0 flex-1">
                {h ? (
                  <button
                    type="button"
                    className="block max-w-full truncate text-left font-heading text-base font-bold text-ink hover:text-accent transition"
                    onClick={(e: MouseEvent<HTMLButtonElement>) => open(h.id, h.name, e.currentTarget)}
                  >
                    {title}
                    {mine && <span className="text-accent font-mono text-xs ml-1">(вы)</span>}
                    {h.dead && <span className="text-bad font-mono text-xs ml-1">· пал</span>}
                  </button>
                ) : (
                  <span className="block truncate font-heading text-base font-bold text-muted">{title}</span>
                )}

                {s.role === "player" && (s.user_name || s.occupant_type === "agent") && (
                  <span className="block font-mono text-[11px] text-muted">
                    {s.occupant_type === "agent" && !s.stand_in ? "ИИ-игрок" : s.user_name}
                    {h ? ` · ур. ${h.level}` : ""}
                    {acting ? <span className="text-accent font-semibold"> · ХОДИТ СЕЙЧАС</span> : ""}
                  </span>
                )}
                <Away seat={s} />
                {h && !h.dead && <Hp h={h} />}
                {h && !h.dead && h.hp === 0 && h.death_saves && (
                  <DeathSaves saves={h.death_saves} label="Без сознания:" />
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Ушёл во время сессии: «переподключается», «вне сети», и кто ведёт героя вместо него. */
function Away({ seat }: { seat: SeatState }) {
  const me = useGame((s) => s.snapshot?.me.user_id);
  if (seat.stand_in && !seat.stand_in.ai)
    return (
      <span className="block font-mono text-[11px] text-warn">
        {seat.user_name} вне сети · {seat.stand_in.user_id === me ? "героя ведёте вы" : `ведёт ${seat.stand_in.name}`}
      </span>
    );
  if (seat.stand_in?.ai && seat.role === "player")
    return <span className="block font-mono text-[11px] text-warn">{seat.user_name} вне сети · героя осторожно ведёт ИИ</span>;
  if (seat.occupant_type !== "human") return null;
  if (seat.presence === "reconnecting") return <span className="block font-mono text-[11px] text-warn">Переподключается…</span>;
  return null;
}

/** Сцена: где отряд и кто рядом. */
export function ScenePanel() {
  const scene = useGame((s) => s.scene);
  const open = useInspector((s) => s.open);
  if (!scene) return null;

  return (
    <section className="card p-4 sm:p-5 border border-line bg-surface flex flex-col gap-3" aria-label="Сцена">
      <div className="flex items-center justify-between border-b border-line pb-2.5">
        <h2 className="font-heading text-lg font-bold text-ink">Сцена и окружение</h2>
        {scene.mode === "combat" && (
          <span className="rounded-full border border-bad/50 bg-bad/10 px-2.5 py-0.5 font-mono text-xs font-semibold text-bad">
            БОЙ · Раунд {scene.round || 1}
          </span>
        )}
      </div>

      {scene.location ? (
        <button
          type="button"
          className="mb-1 block text-left font-heading text-base font-bold text-accent hover:underline decoration-dotted"
          onClick={(e) => open(scene.location!.id, scene.location!.name, e.currentTarget)}
        >
          {TYPE_ICON.location} {scene.location.name}
        </button>
      ) : (
        <p className="font-mono text-xs text-muted">Локация ещё не объявлена мастером.</p>
      )}

      {scene.party && (
        <div className="rounded-[6px] border border-accent/40 bg-accent/5 px-2.5 py-2 text-xs" role="note">
          <p className="font-semibold text-ink">
            {scene.party.some((p) => p.here) ? "Вы отдельно от отряда" : "Отряд разделён"}
          </p>
          <p className="mt-0.5 text-muted">
            Реплики и ответы мастера видят только те, кто рядом. Встретитесь — чат снова станет общим.
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {scene.party.map((p, i) => (
              <li key={i} className={p.here ? "font-semibold text-ink" : "text-muted"}>
                {p.names.join(", ")} — {p.place ?? "неизвестно где"}
                {p.here ? " (вы здесь)" : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {scene.entities.length === 0 ? (
        <p className="font-mono text-xs text-muted">В поле зрения отряда никого нет.</p>
      ) : (
        <ul className="flex flex-col gap-1.5 pt-1">
          {scene.entities.map((e) => {
            const t = sceneType(e);
            const acting = scene.turn?.actor_id === e.id;
            return (
              <li
                key={e.id}
                className="flex items-baseline justify-between gap-2 rounded-[6px] border border-line/40 bg-raised/40 px-2.5 py-1"
              >
                <button
                  type="button"
                  className={`truncate text-left text-xs font-medium underline decoration-dotted underline-offset-4 hover:brightness-125 ${
                    acting ? "font-bold" : ""
                  }`}
                  style={{ color: TYPE_COLOR[t] }}
                  onClick={(ev) => open(e.id, e.name, ev.currentTarget)}
                >
                  {TYPE_ICON[t]} {e.name}
                </button>
                <span className="shrink-0 font-mono text-[10px] text-muted">
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
