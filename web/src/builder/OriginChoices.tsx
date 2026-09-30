import { ABILITY_RU } from "../game/hero";
import type { OriginOption } from "../lib/builder";
import { ChoiceCard, OriginDetails } from "./ChoiceDetails";

interface OriginArtMeta {
  img: string;
  badgeClass: string;
}

// Происхождения мира — только шесть людей. Вторая раса (Сохранивший себя / сердце) приходит в игре через Порог
// и в конструкторе не выбирается; её портреты — для карточки героя после Порога.
const ORIGIN_ART_MAP: Record<string, OriginArtMeta> = {
  "lineage.kept_self": {
    img: "/assets/races/kept_self.png",
    badgeClass: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  },
  "lineage.kept_heart": {
    img: "/assets/races/helmsman.png",
    badgeClass: "bg-teal-500/15 text-teal-300 border-teal-500/30",
  },
  "origin.tushevik": {
    img: "/assets/races/carcass_born.png",
    badgeClass: "bg-amber-600/15 text-amber-300 border-amber-600/30",
  },
  "origin.slomlenny": {
    img: "/assets/races/the_broken.png",
    badgeClass: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  },
  "origin.krovnik": {
    img: "/assets/races/blood_bound.png",
    badgeClass: "bg-rose-600/15 text-rose-300 border-rose-600/30",
  },
  "origin.okrainets": {
    img: "/assets/races/outlander.png",
    badgeClass: "bg-emerald-600/15 text-emerald-300 border-emerald-600/30",
  },
  "origin.morekhod": {
    img: "/assets/races/seafarer.png",
    badgeClass: "bg-sky-600/15 text-sky-300 border-sky-600/30",
  },
  "origin.syndicate": {
    img: "/assets/races/syndicate_heir.png",
    badgeClass: "bg-amber-500/15 text-amber-200 border-amber-500/30",
  },
};

function getOriginArt(o: OriginOption): OriginArtMeta | null {
  if (ORIGIN_ART_MAP[o.id]) return ORIGIN_ART_MAP[o.id];
  const lower = o.name.toLowerCase();
  if (lower.includes("сердц") || lower.includes("кормч")) return ORIGIN_ART_MAP["lineage.kept_heart"];
  if (lower.includes("себя") || lower.includes("сохранивш")) return ORIGIN_ART_MAP["lineage.kept_self"];
  if (lower.includes("тушевик")) return ORIGIN_ART_MAP["origin.tushevik"];
  if (lower.includes("сломленн")) return ORIGIN_ART_MAP["origin.slomlenny"];
  if (lower.includes("кровник")) return ORIGIN_ART_MAP["origin.krovnik"];
  if (lower.includes("окраин")) return ORIGIN_ART_MAP["origin.okrainets"];
  if (lower.includes("мореход")) return ORIGIN_ART_MAP["origin.morekhod"];
  if (lower.includes("синдикат")) return ORIGIN_ART_MAP["origin.syndicate"];
  return null;
}

function formatOriginStats(o: OriginOption): string {
  const parts: string[] = [];
  for (const [a, b] of Object.entries(o.ability_bonuses || {})) {
    parts.push(`${ABILITY_RU[a] ?? a.toUpperCase()} +${b}`);
  }
  for (const g of o.ability_groups || []) {
    parts.push(`+${g.bonus} выбор${g.count > 1 ? ` ×${g.count}` : ""}`);
  }
  return parts.join(", ") || (o.speed ? `скорость ${o.speed} фт.` : "");
}

interface OriginChoicesProps {
  items: OriginOption[];
  value: string;
  onPick: (id: string) => void;
}

export default function OriginChoices({ items, value, onPick }: OriginChoicesProps) {
  return (
    <div className="grid gap-3.5 md:grid-cols-2" role="radiogroup" aria-label="Выбор происхождения">
      {items.map((o) => {
        const on = o.id === value;
        const art = getOriginArt(o);
        const stats = formatOriginStats(o);

        return (
          <ChoiceCard
            key={o.id}
            name={o.name}
            selected={on}
            onPick={() => onPick(o.id)}
            details={<OriginDetails o={o} stats={stats} />}
            className={`group relative flex h-[190px] sm:h-[196px] w-full text-left rounded-[12px] border overflow-hidden transition-all duration-200 cursor-pointer ${
              on
                ? "border-accent bg-surface shadow-[0_4px_24px_rgba(201,138,75,0.24)] ring-1 ring-accent/40"
                : "border-line bg-surface/80 hover:border-accent/60 hover:bg-surface hover:-translate-y-0.5 hover:shadow-lg"
            }`}
          >
            {/* Текстовая колонка слева */}
            <div className="relative z-10 flex flex-1 flex-col justify-between p-3.5 sm:p-4 min-w-0">
              <div className="flex flex-col pr-12 sm:pr-20 md:pr-14">
                <div className="flex items-center gap-1.5">
                  {on && (
                    <span className="font-bold text-accent text-sm leading-none">✓</span>
                  )}
                  <span
                    className={`font-heading text-lg sm:text-xl font-bold leading-tight tracking-tight transition ${
                      on ? "text-accent" : "text-ink group-hover:text-accent"
                    }`}
                  >
                    {o.name}
                  </span>
                </div>

                {o.epithet && (
                  <span className="font-serif italic text-xs text-muted/90 mt-0.5 tracking-wide">
                    {o.epithet}
                  </span>
                )}

                {(o.summary || o.description) && (
                  <p className="mt-1.5 text-xs text-ink/80 line-clamp-3 leading-relaxed">
                    {o.summary || o.description}
                  </p>
                )}
              </div>

              {/* Нижняя строчка: бейдж и бонусы */}
              <div className="flex items-center justify-between gap-2 mt-2 pt-1 border-t border-line/40">
                {o.badge ? (
                  <span
                    className={`shrink-0 whitespace-nowrap font-mono text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded border ${art?.badgeClass ?? "bg-accent/10 text-accent border-accent/30"}`}
                  >
                    {o.badge}
                  </span>
                ) : (
                  <span className="font-mono text-[10px] text-muted">
                    {o.speed ? `${o.speed} фт.` : "—"}
                  </span>
                )}

                {stats && (
                  <span className="font-mono text-[10.5px] text-muted-hi font-medium tracking-tight truncate">
                    {stats}
                  </span>
                )}
              </div>
            </div>

            {/* Иллюстрированный портрет справа с виньеткой */}
            {art?.img && (
              <div className="absolute inset-y-0 right-0 w-32 sm:w-44 md:w-36 overflow-hidden pointer-events-none select-none">
                {/* Мягкая градиентная маска */}
                <div className="absolute inset-0 z-1 bg-gradient-to-r from-surface via-surface/85 to-transparent to-75%" />
                <img
                  src={art.img}
                  alt={o.name}
                  className="w-full h-full object-cover object-top filter brightness-[0.92] contrast-[1.05] group-hover:brightness-100 group-hover:scale-105 transition-all duration-300"
                  loading="lazy"
                />
              </div>
            )}
          </ChoiceCard>
        );
      })}
    </div>
  );
}
