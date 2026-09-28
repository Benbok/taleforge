import { useEffect, useRef, useState } from "react";
import { useGame } from "../stores/game";
import { useExplain } from "./hero";
import { useHeroWindow } from "./HeroWindow";

/** Полоса героя над полем ввода: хиты, КД, эффекты и спасброски от смерти. Каждое число — кнопка с разбором.
 *  Потеря хитов вспыхивает красным с величиной урона, лечение — зелёным. */
export default function HeroHud() {
  const sheet = useGame((s) => s.sheet);
  const explain = useExplain((s) => s.open);
  const showWindow = useHeroWindow((s) => s.show);
  const [flash, setFlash] = useState<{ delta: number; key: number } | null>(null);
  const prev = useRef<number | null>(null);
  const hp = sheet?.resources.hp ?? null;

  useEffect(() => {
    if (hp == null) return;
    if (prev.current != null && hp !== prev.current) {
      setFlash({ delta: hp - prev.current, key: Date.now() });
      const t = setTimeout(() => setFlash(null), 1600);
      prev.current = hp;
      return () => clearTimeout(t);
    }
    prev.current = hp;
  }, [hp]);

  if (!sheet) return null;
  const max = sheet.resources.hp_max ?? sheet.derived?.hp_max ?? 0;
  const temp = sheet.resources.temp_hp ?? 0;
  const pct = max ? Math.max(0, Math.min(100, ((hp ?? 0) / max) * 100)) : 0;
  const color = pct > 50 ? "var(--color-ok)" : pct > 25 ? "var(--color-warn)" : "var(--color-bad)";
  const dying = hp === 0 && !sheet.resources.dead;
  const [succ, fail] = sheet.resources.death_saves ?? [0, 0];
  const effects = sheet.derived?.effects ?? [];

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface px-4 py-2" aria-label="Ваш герой">
      <button className="font-semibold hover:text-accent" onClick={() => showWindow()} title="Открыть лист героя">
        {sheet.name}
      </button>
      <button
        className={`relative flex min-w-[9rem] flex-1 items-center gap-2 rounded-md px-1 sm:max-w-xs ${
          flash && flash.delta < 0 ? "ring-2 ring-bad" : flash ? "ring-2 ring-ok" : ""
        }`}
        onClick={(e) => explain("hp", e.currentTarget)}
        title="Хиты: почему столько"
      >
        <span className="text-xs text-muted">Хиты</span>
        <span className="h-2 flex-1 overflow-hidden rounded-full bg-raised">
          <span className="block h-full transition-[width] duration-500" style={{ width: `${pct}%`, background: color }} />
        </span>
        <span className="tabular-nums">
          {hp ?? "—"}/{max}
          {temp > 0 && <span className="text-npc"> +{temp}</span>}
        </span>
        {flash && (
          <span
            key={flash.key}
            className={`tf-pop absolute -top-5 right-0 text-sm font-bold ${flash.delta < 0 ? "text-bad" : "text-ok"}`}
            aria-live="assertive"
          >
            {flash.delta > 0 ? `+${flash.delta}` : flash.delta}
          </span>
        )}
      </button>
      <button className="flex items-baseline gap-1" onClick={(e) => explain("ac", e.currentTarget)} title="Класс доспеха: почему столько">
        <span className="text-xs text-muted">КД</span>
        <span className="font-semibold tabular-nums">{sheet.derived?.ac ?? "—"}</span>
      </button>
      {dying && (
        <span className="flex items-center gap-1 text-xs" title="Спасброски от смерти: три успеха — стабилизация, три провала — смерть">
          <span className="text-bad">При смерти:</span>
          {[0, 1, 2].map((i) => (
            <span key={`s${i}`} className={`h-2.5 w-2.5 rounded-full border border-ok ${i < succ ? "bg-ok" : ""}`} />
          ))}
          <span className="mx-0.5 text-muted">/</span>
          {[0, 1, 2].map((i) => (
            <span key={`f${i}`} className={`h-2.5 w-2.5 rounded-full border border-bad ${i < fail ? "bg-bad" : ""}`} />
          ))}
        </span>
      )}
      {sheet.resources.dead && <span className="text-bad">Герой пал</span>}
      {effects.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {effects.map((e) => (
            <button
              key={e.id}
              className="rounded-full border border-line px-2 py-0.5 text-xs hover:border-accent"
              onClick={() => showWindow("state")}
            >
              {e.name}
              {e.stacks > 1 ? ` ×${e.stacks}` : ""}
            </button>
          ))}
        </span>
      )}
      <button className="btn ml-auto px-2 py-1 text-xs" onClick={() => showWindow()}>
        Лист героя
      </button>
    </div>
  );
}
