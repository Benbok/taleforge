import type { MouseEvent } from "react";
import Avatar from "../components/Avatar";
import type { CompanionPublic, EntityType, HeroPublic, SceneEntity, SeatState } from "../lib/types";
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

function CompanionRow({ companion, onOpen }: { companion: CompanionPublic; onOpen: (id: string, name: string, el: HTMLElement) => void }) {
  const hp = companion.hp != null && companion.hp_max ? `${companion.hp} / ${companion.hp_max}` : null;
  const pct = companion.hp != null && companion.hp_max ? Math.max(0, Math.min(100, (companion.hp / companion.hp_max) * 100)) : 0;
  return (
    <div className="mt-1.5 rounded-[6px] border border-line/50 bg-surface/80 p-1.5" data-testid="companion-row">
      <div className="flex items-center justify-between gap-1">
        <button
          type="button"
          title={companion.name}
          className="min-w-0 flex-1 truncate text-left text-xs font-semibold text-ink hover:text-accent transition"
          onClick={(e) => onOpen(companion.id, companion.name, e.currentTarget)}
        >
          ◇ {companion.name}
        </button>
        <span className="font-mono text-[9px] text-muted uppercase tracking-wider shrink-0">спутник</span>
      </div>
      {hp && (
        <div className="mt-1" title={`Хиты ${hp}`}>
          <div className="h-1 overflow-hidden rounded-full bg-raised">
            <div className="h-full bg-patina transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-0.5 flex justify-between font-mono text-[9px] text-muted tabular-nums">
            <span>HP</span><span>{hp}</span>
          </div>
        </div>
      )}
      {companion.down && <span className="block font-mono text-[10px] text-warn">без сознания</span>}
      {companion.dead && <span className="block font-mono text-[10px] text-bad">пал</span>}
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
    <section className="card p-3 sm:p-3.5 border border-line bg-surface flex flex-col gap-2.5" aria-label="Отряд">
      <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
        <h2 className="font-heading text-sm sm:text-base font-bold text-ink whitespace-nowrap">Отряд экспедиции</h2>
        <span className="rounded-full bg-raised/80 px-2 py-0.5 font-mono text-[11px] text-muted shrink-0 whitespace-nowrap">
          {sorted.filter((s) => s.role === "player").length} мест
        </span>
      </div>

      <ul className="flex flex-col gap-2">
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
              className={`flex items-start gap-2.5 rounded-[8px] p-2 transition ${
                acting
                  ? "bg-accent/10 border border-accent shadow-[0_0_10px_rgba(201,138,75,0.15)] ring-1 ring-accent/40"
                  : "border border-line/60 bg-raised/30 hover:border-line"
              }`}
            >
              <Avatar
                name={h?.name ?? s.user_name}
                role={s.role}
                occupant={s.occupant_type}
                presence={s.occupant_type === "human" ? (s.presence ?? "offline") : null}
                size={30}
              />

              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-1.5">
                  {h ? (
                    <button
                      type="button"
                      title={title}
                      className="min-w-0 flex-1 text-left font-heading text-sm font-bold text-ink hover:text-accent transition leading-snug break-words"
                      onClick={(e: MouseEvent<HTMLButtonElement>) => open(h.id, h.name, e.currentTarget)}
                    >
                      {title}
                    </button>
                  ) : (
                    <span className="min-w-0 flex-1 font-heading text-sm font-bold text-muted leading-snug break-words" title={title}>
                      {title}
                    </span>
                  )}

                  <div className="flex items-center gap-1 shrink-0 pt-0.5">
                    {mine && (
                      <span className="rounded bg-accent/15 px-1.5 py-0.2 font-mono text-[10px] font-semibold text-accent">
                        вы
                      </span>
                    )}
                    {h?.dead && (
                      <span className="rounded bg-bad/15 px-1.5 py-0.2 font-mono text-[10px] font-semibold text-bad">
                        пал
                      </span>
                    )}
                  </div>
                </div>

                {s.role === "player" && (s.user_name || s.occupant_type === "agent") && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-1 font-mono text-[11px] text-muted">
                    <span className="truncate max-w-[110px]" title={s.user_name ?? undefined}>
                      {s.occupant_type === "agent" && !s.stand_in ? "ИИ-игрок" : s.user_name}
                    </span>
                    {h && <span>· ур. {h.level}</span>}
                    {acting && (
                      <span className="rounded bg-accent/20 px-1 py-0.2 font-mono text-[10px] font-bold text-accent animate-pulse">
                        ХОД
                      </span>
                    )}
                  </div>
                )}
                <Away seat={s} />
                {h && !h.dead && <Hp h={h} />}
                {h && !h.dead && h.hp === 0 && h.death_saves && (
                  <DeathSaves saves={h.death_saves} label="Без сознания:" />
                )}
                {h?.companions?.map((companion) => (
                  <CompanionRow key={companion.id} companion={companion} onOpen={open} />
                ))}
              </div>
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
export function ScenePanel({ onReturnToStory }: { onReturnToStory?: () => void } = {}) {
  const scene = useGame((s) => s.scene);
  const open = useInspector((s) => s.open);
  if (!scene)
    return (
      <section className="card border border-line bg-surface p-5" aria-label="Сцена">
        <h2 className="font-heading text-xl font-bold text-ink">История ещё не началась</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Когда мастер опишет сцену, здесь появятся место, персонажи и предметы рядом с отрядом.
        </p>
        {onReturnToStory && (
          <button type="button" className="btn btn-outline-copper mt-4 min-h-11" onClick={onReturnToStory}>
            К истории
          </button>
        )}
      </section>
    );

  return (
    <section className="card flex flex-col gap-3 border border-line bg-surface p-4 sm:p-5" aria-label="Сцена">
      <div className="flex items-center justify-between border-b border-line pb-2.5">
        <h2 className="font-heading text-lg font-bold text-ink">Сцена и окружение</h2>
        {scene.mode === "combat" && (
          <span className="rounded-full border border-bad/50 bg-bad/10 px-2.5 py-0.5 font-mono text-xs font-semibold text-bad">
            БОЙ · Раунд {scene.round || 1}
          </span>
        )}
      </div>

      {/* Карточка локации */}
      {scene.location ? (
        <button
          type="button"
          className="group flex w-full items-center justify-between gap-2.5 rounded-lg border border-line/70 bg-raised/40 p-2.5 text-left transition-all hover:border-accent/60 hover:bg-raised/70"
          onClick={(e) => open(scene.location!.id, scene.location!.name, e.currentTarget)}
          title="Осмотреть текущую локацию"
        >
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-place/40 bg-place/10 text-sm font-bold text-place">
              {TYPE_ICON.location}
            </span>
            <div className="min-w-0">
              <span className="block font-mono text-[9px] uppercase tracking-wider text-muted">Локация</span>
              <span className="block truncate font-heading text-sm font-bold text-ink transition-colors group-hover:text-accent">
                {scene.location.name}
              </span>
            </div>
          </div>
          <span className="shrink-0 font-mono text-[10px] text-muted transition-colors group-hover:text-accent">
            Инфо →
          </span>
        </button>
      ) : (
        <div className="rounded-lg border border-dashed border-line/70 p-2.5 text-center font-mono text-xs text-muted">
          Локация ещё не объявлена мастером.
        </div>
      )}

      {/* Разделение отряда */}
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

      {/* Список сущностей сцены в виде интерактивных мини-карточек */}
      {scene.entities.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line/60 py-6 text-center text-muted">
          <span className="font-mono text-base opacity-40">◇</span>
          <p className="font-mono text-xs">В поле зрения отряда никого нет</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2 pt-1">
          {scene.entities.map((e) => {
            const t = sceneType(e);
            const acting = scene.turn?.actor_id === e.id;
            return (
              <li key={e.id}>
                <button
                  type="button"
                  className={`group flex w-full flex-col gap-1.5 rounded-lg border p-2.5 text-left transition-all ${
                    acting
                      ? "border-accent/80 bg-accent/10 shadow-xs ring-1 ring-accent/30"
                      : t === "creature"
                        ? "border-bad/30 bg-bad/5 hover:border-bad/60 hover:bg-bad/10"
                        : t === "item"
                          ? "border-item/30 bg-item/5 hover:border-item/60 hover:bg-item/10"
                          : "border-line/70 bg-raised/40 hover:border-accent/60 hover:bg-raised/70"
                  }`}
                  onClick={(ev) => open(e.id, e.name, ev.currentTarget)}
                  title={`Осмотреть: ${e.name}`}
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span
                        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md font-mono text-xs font-bold"
                        style={{
                          color: TYPE_COLOR[t],
                          backgroundColor: `color-mix(in srgb, ${TYPE_COLOR[t]} 15%, transparent)`,
                        }}
                      >
                        {e.companion_of ? "◇" : TYPE_ICON[t]}
                      </span>
                      <span
                        className={`truncate font-heading text-xs font-semibold text-ink transition-colors group-hover:text-accent ${
                          acting ? "font-bold" : ""
                        }`}
                      >
                        {e.name}
                      </span>
                      {e.companion_of && (
                        <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider text-muted">
                          спутник
                        </span>
                      )}
                      {e.qty && e.qty > 1 && (
                        <span className="shrink-0 font-mono text-[10px] text-muted">
                          ×{e.qty}
                        </span>
                      )}
                    </div>
                    {acting ? (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded border border-accent/40 bg-accent/20 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-accent animate-pulse">
                        ● Ходит
                      </span>
                    ) : (
                      <span className="shrink-0 font-mono text-[10px] text-muted opacity-0 transition-opacity group-hover:opacity-100">
                        🔍
                      </span>
                    )}
                  </div>

                  {/* Бейджи статуса, зоны и состояний */}
                  {(e.zone || e.condition || e.attitude) && (
                    <div className="flex flex-wrap items-center gap-1 pl-6 text-[10px] font-mono">
                      {e.zone && (
                        <span className="rounded border border-line/50 bg-surface/80 px-1.5 py-0.5 text-muted">
                          📍 {e.zone}
                        </span>
                      )}
                      {e.condition && (
                        <span
                          className={`rounded border px-1.5 py-0.5 ${
                            e.condition.includes("ранен") || e.condition.includes("сознан") || e.condition.includes("убит")
                              ? "border-bad/40 bg-bad/10 text-bad font-semibold"
                              : "border-warn/40 bg-warn/10 text-warn"
                          }`}
                        >
                          {e.condition}
                        </span>
                      )}
                      {e.attitude === "hostile" && (
                        <span className="rounded border border-bad/30 bg-bad/10 px-1.5 py-0.5 text-bad">
                          враждебный
                        </span>
                      )}
                      {e.attitude === "friendly" && (
                        <span className="rounded border border-ok/30 bg-ok/10 px-1.5 py-0.5 text-ok">
                          союзник
                        </span>
                      )}
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
