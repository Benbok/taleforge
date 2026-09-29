import { useState } from "react";
import { initials } from "../components/Avatar";
import type { OrderEntry, SceneEntity } from "../lib/types";
import { useGame } from "../stores/game";
import { byZone, myTurn, ringState, TONE_COLOR, useTurnClock, ZONES } from "./combat";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";

/** Кольцо таймера вокруг жетона того, кто ходит. */
export function TurnRing({ left, total, size = 44 }: { left: number; total: number; size?: number }) {
  const { pct, tone } = ringState(left, total);
  const r = size / 2 - 3;
  const len = 2 * Math.PI * r;
  return (
    <svg
      width={size}
      height={size}
      className={`pointer-events-none absolute inset-0 -rotate-90 ${tone === "urgent" ? "tf-blink" : ""}`}
      aria-hidden
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={3} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={TONE_COLOR[tone]}
        strokeWidth={3}
        strokeLinecap="round"
        strokeDasharray={len}
        strokeDashoffset={len * (1 - pct)}
        style={{ transition: "stroke-dashoffset 250ms linear, stroke 300ms" }}
      />
    </svg>
  );
}

const SIDE_COLOR = { hero: "var(--tf-accent)", enemy: "var(--tf-entity-creature)", ally: "var(--tf-entity-npc)" };

function Token({ e, acting, mine }: { e: OrderEntry; acting: boolean; mine: boolean }) {
  const open = useInspector((s) => s.open);
  const turn = useGame((s) => s.turn);
  const clock = useTurnClock(acting ? turn : null);
  const secs = clock ? Math.ceil(clock.left) : null;
  return (
    <li className="shrink-0">
      <button
        className={`flex w-[5.5rem] flex-col items-center gap-1 rounded-md px-1 py-1 text-center ${acting ? "bg-raised" : ""} ${e.out ? "opacity-45" : ""}`}
        onClick={(ev) => open(e.id, e.name, ev.currentTarget)}
        title={`${e.name}${e.initiative != null ? `, инициатива ${e.initiative}` : ""}${e.out ? `, ${e.out}` : ""}`}
        aria-current={acting ? "true" : undefined}
      >
        <span className="relative flex h-11 w-11 items-center justify-center">
          {clock && <TurnRing left={clock.left} total={clock.total} />}
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-semibold"
            style={{ borderColor: SIDE_COLOR[e.side], color: SIDE_COLOR[e.side] }}
          >
            {initials(e.name)}
          </span>
        </span>
        <span className={`line-clamp-2 w-full break-words text-xs leading-tight ${acting ? "font-semibold" : ""}`}>
          {e.name}
          {mine && " (вы)"}
        </span>
        <span className="text-[10px] leading-none text-muted">
          {e.out ?? (secs != null ? `${secs} с` : e.initiative != null ? `иниц. ${e.initiative}` : "")}
        </span>
      </button>
    </li>
  );
}

function ZoneToken({ e }: { e: SceneEntity }) {
  const open = useInspector((s) => s.open);
  const hostile = e.attitude === "hostile";
  const color = hostile ? TYPE_COLOR.creature : TYPE_COLOR.npc;
  const dead = e.condition === "мёртв";
  return (
    <button
      className={`max-w-full truncate rounded-full border px-2 py-0.5 text-xs ${dead ? "line-through opacity-50" : ""}`}
      style={{ borderColor: color, color }}
      onClick={(ev) => open(e.id, e.name, ev.currentTarget)}
      title={[e.name, e.condition].filter(Boolean).join(", ")}
    >
      {hostile ? TYPE_ICON.creature : TYPE_ICON.npc} {e.name}
    </button>
  );
}

function NotifyButton() {
  const [perm, setPerm] = useState(() => (typeof Notification === "undefined" ? "denied" : Notification.permission));
  if (perm !== "default") return null;
  return (
    <button
      className="text-xs text-muted underline"
      onClick={() => Notification.requestPermission().then(setPerm, () => setPerm("denied"))}
      title="Уведомление придёт, если вкладка свёрнута"
    >
      Уведомлять о моём ходе
    </button>
  );
}

/** Полоса боя над чатом: очередь инициативы с кольцом таймера у того, кто ходит, и зоны относительно отряда. */
export default function CombatStrip() {
  const scene = useGame((s) => s.scene);
  const turn = useGame((s) => s.turn);
  const seat = useGame((s) => s.snapshot?.me?.seat_id);
  if (!scene || scene.mode !== "combat") return null;
  const order = scene.order ?? [];
  const zones = byZone(scene.entities);
  const mine = myTurn(turn, seat);
  return (
    <section className="border-b border-line bg-surface px-3 py-2" aria-label="Бой">
      <div className="mb-1 flex items-center gap-3 text-xs">
        <span className="font-semibold text-bad">Бой · раунд {scene.round || 1}</span>
        <span className={mine ? "font-semibold text-accent" : "text-muted"}>
          {turn ? (mine ? "Ваш ход" : `Ходит: ${turn.name}`) : ""}
        </span>
        <span className="ml-auto">
          <NotifyButton />
        </span>
      </div>
      <ol className="flex gap-1 overflow-x-auto pb-1" aria-label="Очередь инициативы">
        {order.map((e) => (
          <Token key={e.id} e={e} acting={turn?.actor_id === e.id} mine={!!seat && e.seat_id === seat} />
        ))}
      </ol>
      <div className="mt-1 grid grid-cols-3 items-start gap-2 text-xs sm:grid-cols-[auto_1fr_1fr_1fr]" aria-label="Зоны">
        <span className="hidden rounded-md bg-raised px-2 py-1 font-semibold sm:block" style={{ color: SIDE_COLOR.hero }}>
          Отряд
        </span>
        {ZONES.map((z) => (
          <div key={z} className="min-w-0 rounded-md border border-dashed border-line px-1.5 py-1">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">{z}</div>
            <div className="flex flex-wrap gap-1">
              {zones[z].length ? zones[z].map((e) => <ZoneToken key={e.id} e={e} />) : <span className="text-muted">—</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
