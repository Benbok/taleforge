// Бой на экране: таймер хода, зоны и оповещения «Ваш ход». Числа и очередь присылает сервер, клиент только рисует.
import { useEffect, useRef, useState } from "react";
import type { SceneEntity, Turn, TurnEconomy } from "../lib/types";
import { useGame } from "../stores/game";

export const WARN_SEC = 60;
export const URGENT_SEC = 15;
export const ZONES = ["вплотную", "близко", "далеко"] as const;

export type Tone = "calm" | "warn" | "urgent";

/** Кольцо таймера: доля оставшегося времени и цвет. За 60 с — жёлтое, за 15 с — красное и мигает. */
export function ringState(left: number, total: number): { pct: number; tone: Tone } {
  const pct = total > 0 ? Math.max(0, Math.min(1, left / total)) : 0;
  const tone: Tone = left <= URGENT_SEC ? "urgent" : left <= WARN_SEC ? "warn" : "calm";
  return { pct, tone };
}

export const TONE_COLOR: Record<Tone, string> = {
  calm: "var(--color-accent)",
  warn: "var(--color-warn)",
  urgent: "var(--color-bad)",
};

/** Существа сцены по зонам «вплотную / близко / далеко» относительно отряда. Сбежавших и неизвестные зоны — в «далеко». */
export function byZone(entities: SceneEntity[]): Record<(typeof ZONES)[number], SceneEntity[]> {
  const out = { вплотную: [], близко: [], далеко: [] } as Record<(typeof ZONES)[number], SceneEntity[]>;
  for (const e of entities) {
    if (e.kind === "item") continue;
    const z = (ZONES as readonly string[]).includes(e.zone) ? (e.zone as (typeof ZONES)[number]) : "далеко";
    out[z].push(e);
  }
  return out;
}

export function turnKey(t: Turn | null): string | null {
  return t ? `${t.round}:${t.actor_id}:${t.deadline ?? ""}` : null;
}

/** Секунды до конца хода и полная длина хода (первое увиденное значение этого хода). */
export function useTurnClock(turn: Turn | null): { left: number; total: number } | null {
  const [now, setNow] = useState(() => Date.now());
  const totals = useRef(new Map<string, number>());
  const active = !!turn?.deadline;
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [active]);
  if (!turn?.deadline) return null;
  const left = Math.max(0, turn.deadline - now / 1000);
  const key = turnKey(turn)!;
  if (!totals.current.has(key)) totals.current.set(key, Math.max(left, 1));
  return { left, total: totals.current.get(key)! };
}

/** Что осталось у героя в этот ход: подписи для полосы боя, ``spent`` — уже потрачено. */
export function turnLeft(e: TurnEconomy): { label: string; spent: boolean }[] {
  const action = e.attacks_left > 0 ? `Атака: ещё ${e.attacks_left}` : "Действие";
  return [
    { label: action, spent: !e.action && e.attacks_left === 0 },
    { label: "Бонусное", spent: !e.bonus },
    { label: `Шаги ${e.move_left_ft} фт`, spent: e.move_left_ft === 0 },
    ...(e.disengage ? [{ label: "Отход", spent: false }] : []),
  ];
}

export function myTurn(turn: Turn | null, seatId: string | null | undefined): boolean {
  return !!turn && !!seatId && turn.seat_id === seatId;
}

function notify(text: string): void {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted" && document.hidden) {
      new Notification("Taleforge", { body: text, tag: "tf-turn" });
    }
  } catch {
    // уведомления недоступны: остаются заголовок вкладки и кольцо
  }
}

/** «Ваш ход» в заголовке вкладки и системное уведомление, если вкладка свёрнута: в начале хода и за 15 с до конца. */
export function useTurnAlerts(): void {
  const turn = useGame((s) => s.turn);
  const seat = useGame((s) => s.snapshot?.me?.seat_id);
  const mine = myTurn(turn, seat);
  const clock = useTurnClock(mine ? turn : null);
  const key = mine ? turnKey(turn) : null;
  const warned = useRef<string | null>(null);

  useEffect(() => {
    if (!key) return;
    const base = document.title.replace(/^● Ваш ход · /, "");
    document.title = `● Ваш ход · ${base}`;
    notify("Ваш ход");
    return () => {
      document.title = document.title.replace(/^● Ваш ход · /, "");
    };
  }, [key]);

  const urgent = !!clock && clock.left <= URGENT_SEC && clock.left > 0;
  useEffect(() => {
    if (urgent && key && warned.current !== key) {
      warned.current = key;
      notify(`До конца хода ${URGENT_SEC} секунд`);
    }
  }, [urgent, key]);
}
