import { ABILITY_RU } from "../game/hero";
import { COMPONENT_RU, type SpellCard } from "../lib/spells";

const AREA_RU: Record<string, string> = { cone: "конус", sphere: "сфера", cube: "куб", line: "линия", cylinder: "цилиндр" };

/** Подробности заклинания: свойства, как выглядит в мире, что делает и что даёт высокая ячейка. */
export default function SpellDetails({ s }: { s: SpellCard }) {
  const rows: [string, string | null][] = [
    ["Круг", s.level === 0 ? "заговор" : `${s.level}-й`],
    ["Школа", s.school],
    ["Время", s.casting_time + (s.ritual ? " (можно ритуалом)" : "")],
    ["Дистанция", s.range],
    ["Область", s.area ? `${AREA_RU[s.area.shape] ?? s.area.shape}, ${s.area.size_ft} фт` : null],
    ["Компоненты", s.components.map((c) => COMPONENT_RU[c] ?? c).join(", ")],
    ["Длительность", s.duration + (s.concentration ? ", концентрация" : "")],
    ["Бросок", s.attack ? (s.attack === "melee" ? "рукопашная атака заклинанием" : "дальнобойная атака заклинанием") : null],
    ["Спасбросок", s.save ? `${ABILITY_RU[s.save] ?? s.save} цели` : null],
  ];
  return (
    <div className="flex flex-col gap-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="text-ink">{v}</dd>
            </div>
          ))}
      </dl>
      {s.flavor && <p className="font-serif italic text-xs text-accent/90 leading-relaxed">{s.flavor}</p>}
      <p className="whitespace-pre-line leading-relaxed text-ink/90">{s.description}</p>
      {s.higher_levels && (
        <p className="border-t border-line/60 pt-2 text-xs leading-relaxed text-ink/85">
          <span className="font-semibold text-ink">На высоких кругах. </span>
          {s.higher_levels}
        </p>
      )}
      {s.material && s.components.includes("M") && (
        <p className="text-xs text-muted">Материал: {s.material}</p>
      )}
      {!s.combat && (
        <p className="text-xs text-warn">
          Творится {s.casting_time}: в бою не успеть, только вне боя.
        </p>
      )}
    </div>
  );
}
