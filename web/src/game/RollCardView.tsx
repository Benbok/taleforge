import { useState } from "react";
import type { RollCard } from "../lib/types";

const OUTCOME: Record<string, { text: string; cls: string }> = {
  success: { text: "Успех", cls: "text-ok" },
  fail: { text: "Провал", cls: "text-bad" },
  hit: { text: "Попадание", cls: "text-ok" },
  crit: { text: "Критическое попадание", cls: "text-ok" },
  miss: { text: "Промах", cls: "text-bad" },
};
const MODE: Record<string, string> = { advantage: "с преимуществом", disadvantage: "с помехой" };

/** Карточка броска: что проверялось, кубик, итог против сложности, успех или провал цветом; по нажатию — разбор. */
export default function RollCardView({ card }: { card: RollCard }) {
  const [open, setOpen] = useState(false);
  const out = OUTCOME[card.outcome];
  const roll = card.roll;
  return (
    <div className="tf-pop mx-auto w-full max-w-md">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-left hover:border-accent"
      >
        {roll?.total != null ? (
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md border-2 text-lg font-semibold ${
              card.outcome === "fail" || card.outcome === "miss" ? "border-bad" : card.outcome === "info" ? "border-line" : "border-ok"
            }`}
            aria-label={`итог ${roll.total}`}
          >
            {roll.total}
          </span>
        ) : (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border-2 border-line text-lg" aria-hidden>
            ⚄
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{card.title}</span>
          <span className="block truncate text-xs text-muted">
            {[card.who, card.target && `→ ${card.target}`, card.against && `против ${card.against.label} ${card.against.value}`]
              .filter(Boolean)
              .join(" ")}
            {card.order && card.order.map((x) => `${x.name ?? "?"} ${x.initiative}`).join(" · ")}
          </span>
        </span>
        <span className="shrink-0 text-right">
          {out && <span className={`block font-semibold ${out.cls}`}>{out.text}</span>}
          {card.damage && <span className="block text-xs">урон {card.damage.amount}</span>}
        </span>
      </button>
      {open && (
        <div className="mt-1 rounded-lg border border-line bg-raised px-3 py-2 text-xs leading-relaxed">
          {roll?.natural != null && (
            <p>
              d20: {roll.d20 && roll.d20.length > 1 ? `${roll.d20.join(" и ")} → ` : ""}
              {roll.natural}
              {roll.modifier ? ` ${roll.modifier > 0 ? "+" : "−"} ${Math.abs(roll.modifier)}` : ""} = {roll.total}
              {roll.mode && MODE[roll.mode] ? ` (${MODE[roll.mode]})` : ""}
            </p>
          )}
          {card.damage && (
            <p>
              Урон: {card.damage.dice.map((d) => `${d.expr} = ${d.total}`).join(", ")} — всего {card.damage.amount}
              {card.damage.type ? `, ${card.damage.type}` : ""}
            </p>
          )}
          {card.dice && card.dice.length > 0 && <p>Кубики: {card.dice.map((d) => `${d.expr} = ${d.total}`).join(", ")}</p>}
          {card.track && (
            <p>
              Успехи {card.track.successes} из 3 · провалы {card.track.failures} из 3
            </p>
          )}
          {card.reason && <p className="text-muted">Зачем: {card.reason}</p>}
          {card.notes?.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}
    </div>
  );
}
