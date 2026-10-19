import { useEffect, useRef, useState } from "react";
import { useGame } from "../stores/game";
import DeathSaves from "./DeathSaves";
import { useExplain } from "./hero";
import { useHeroWindow } from "./HeroWindow";
import { useInspector } from "./inspector";

/** Полоса героя над полем ввода: хиты, КД, эффекты и спасброски от смерти. Каждое число — кнопка с разбором.
 *  Потеря хитов вспыхивает красным с величиной урона, лечение — зелёным. */
export default function HeroHud() {
  const sheet = useGame((s) => s.sheet);
  const explain = useExplain((s) => s.open);
  const showWindow = useHeroWindow((s) => s.show);
  const inspect = useInspector((s) => s.open);
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
  const slotsInfo = slotsNote(sheet.spellbook);

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line/80 bg-surface/95 px-3 py-2 shadow-[0_-2px_8px_rgba(0,0,0,0.12)] backdrop-blur-xs sm:px-4"
      aria-label="Ваш герой"
    >
      {/* Карточка героя: имя и уровень */}
      <button
        className="group flex items-center gap-2 rounded-lg border border-line/60 bg-raised/50 px-2.5 py-1 text-left transition-colors hover:border-accent/70 hover:bg-raised"
        onClick={() => showWindow()}
        title="Открыть лист героя"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-accent/40 bg-accent/10 font-mono text-[10px] text-accent">
          ◈
        </span>
        <span className="font-heading text-sm font-bold text-ink transition-colors group-hover:text-accent">
          {sheet.name}
        </span>
        {sheet.sheet?.level != null && (
          <span className="font-mono text-[10px] text-muted">
            {sheet.sheet.level} ур.
          </span>
        )}
      </button>

      {/* Класс доспеха: щит с КД */}
      <button
        className="group flex items-center gap-1.5 rounded-lg border border-line/60 bg-raised/50 px-2.5 py-1 text-xs transition-colors hover:border-accent/70 hover:bg-raised"
        onClick={(e) => explain("ac", e.currentTarget)}
        title="Класс доспеха: почему столько"
      >
        <svg
          className="h-3.5 w-3.5 shrink-0 text-accent/80 transition-colors group-hover:text-accent"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">КД</span>
        <span className="font-mono font-bold tabular-nums text-ink">{sheet.derived?.ac ?? "—"}</span>
      </button>

      {/* Хиты: шкала здоровья с сердечком */}
      <button
        className={`relative flex min-w-[9.5rem] flex-1 items-center gap-2 rounded-lg border border-line/60 bg-raised/50 px-2.5 py-1 text-xs transition-colors hover:border-accent/70 sm:max-w-xs ${
          flash && flash.delta < 0 ? "ring-2 ring-bad" : flash ? "ring-2 ring-ok" : ""
        }`}
        onClick={(e) => explain("hp", e.currentTarget)}
        title="Хиты: почему столько"
      >
        <svg className="h-3.5 w-3.5 shrink-0 text-bad" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
        </svg>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">ХП</span>
        <span className="h-2 flex-1 overflow-hidden rounded-full border border-line/40 bg-bg">
          <span
            className="block h-full rounded-full transition-[width] duration-500"
            style={{ width: `${pct}%`, background: color }}
          />
        </span>
        <span className="font-mono text-xs tabular-nums text-ink">
          {hp ?? "—"}/{max}
          {temp > 0 && <span className="font-semibold text-npc"> +{temp}</span>}
        </span>
        {flash && (
          <span
            key={flash.key}
            className={`tf-pop absolute -top-5 right-0 rounded border px-1.5 py-0.2 text-xs font-bold shadow-xs ${
              flash.delta < 0 ? "border-bad/50 bg-bad/20 text-bad" : "border-ok/50 bg-ok/20 text-ok"
            }`}
            aria-live="assertive"
          >
            {flash.delta > 0 ? `+${flash.delta}` : flash.delta}
          </span>
        )}
      </button>

      {/* Спасброски от смерти */}
      {dying && <DeathSaves saves={[succ, fail]} />}
      {sheet.resources.dead && (
        <span className="inline-flex items-center gap-1 rounded border border-bad/40 bg-bad/10 px-2 py-0.5 font-mono text-xs font-bold uppercase tracking-wider text-bad">
          ☠ Герой пал
        </span>
      )}

      {/* Рунические чипы эффектов */}
      {effects.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Состояния и эффекты">
          {effects.map((e) => (
            <button
              key={e.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/90 px-2.5 py-0.5 text-xs text-ink transition-colors hover:border-accent hover:bg-raised shadow-2xs"
              onClick={(event) => inspect(e.template, e.name, event.currentTarget)}
              title={[e.source && `Источник: ${e.source}`, e.reason].filter(Boolean).join(". ") || "Описание состояния / эффекта"}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              {e.name}
              {e.stacks > 1 ? ` ×${e.stacks}` : ""}
            </button>
          ))}
        </div>
      )}

      {/* Кнопка книги заклинаний */}
      {sheet.spellbook && (
        <button
          className="btn group ml-auto flex items-center gap-1.5 border border-line/70 px-2.5 py-1 text-xs transition-colors hover:border-accent/70"
          onClick={() => showWindow("spells")}
          title="Книга заклинаний: ячейки, описания и сотворение"
        >
          <svg
            className="h-3.5 w-3.5 shrink-0 text-accent transition-transform group-hover:rotate-12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          <span>Заклинания</span>
          {slotsInfo.text && (
            <span className="font-mono text-[10px] text-accent tracking-tighter" title={`Доступно ячеек: ${slotsInfo.left} из ${slotsInfo.all}`}>
              {slotsInfo.pips} <span className="tabular-nums font-semibold">{slotsInfo.text}</span>
            </span>
          )}
        </button>
      )}

      {/* Кнопка Листа героя */}
      <button
        className={`btn flex items-center gap-1.5 border border-line/70 px-2.5 py-1 text-xs transition-colors hover:border-accent/70 ${
          sheet.spellbook ? "" : "ml-auto"
        }`}
        onClick={() => showWindow()}
        title="Открыть полный лист персонажа"
      >
        <svg
          className="h-3.5 w-3.5 shrink-0 text-muted"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span>Лист героя</span>
      </button>
    </div>
  );
}

/** Сколько ячеек осталось и визуальные кристаллы ячеек ◆ / ◇ */
function slotsNote(b: NonNullable<ReturnType<typeof useGame.getState>["sheet"]>["spellbook"]): {
  left: number;
  all: number;
  text: string;
  pips: string;
} {
  if (!b) return { left: 0, all: 0, text: "", pips: "" };
  const left = Object.values(b.slots_left).reduce((a, x) => a + x, 0) + (b.pact_slots ? b.pact_left : 0);
  const all = b.slots.reduce((a, x) => a + x, 0) + b.pact_slots;
  if (!all) return { left: 0, all: 0, text: "", pips: "" };
  const maxPips = Math.min(all, 5);
  const filledPips = Math.min(left, maxPips);
  const emptyPips = maxPips - filledPips;
  const pips = "◆".repeat(filledPips) + "◇".repeat(emptyPips);
  return { left, all, text: `· ${left}/${all}`, pips };
}
