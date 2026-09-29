import { ABILITY_ABBR, ABILITY_RU } from "../game/hero";
import type { ClassOption } from "../lib/builder";

interface ClassArtMeta {
  img: string;
  sub: string;
  badge: string;
  badgeClass: string;
}

const CLASS_ART_MAP: Record<string, ClassArtMeta> = {
  "class.diagnost": {
    img: "/assets/classes/diagnost.png",
    sub: "Guild Diagnost",
    badge: "Гильдия · Ликвор",
    badgeClass: "bg-teal-500/15 text-teal-300 border-teal-500/30",
  },
  "class.barbarian": {
    img: "/assets/classes/barbarian.png",
    sub: "Mutagen Berserker",
    badge: "Мутагены",
    badgeClass: "bg-amber-600/15 text-amber-300 border-amber-600/30",
  },
  "class.bard": {
    img: "/assets/classes/bard.png",
    sub: "Resonance Echolocator",
    badge: "Колокола · Эхо",
    badgeClass: "bg-yellow-500/15 text-yellow-300 border-yellow-500/30",
  },
  "class.cleric": {
    img: "/assets/classes/cleric.png",
    sub: "Priest of the Giants",
    badge: "Церковь · Сны",
    badgeClass: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  },
  "class.druid": {
    img: "/assets/classes/druid.png",
    sub: "Parasite Shepherd",
    badge: "Паразиты",
    badgeClass: "bg-emerald-600/15 text-emerald-300 border-emerald-600/30",
  },
  "class.fighter": {
    img: "/assets/classes/fighter.png",
    sub: "Cordon Purger",
    badge: "Кордон · Огонь",
    badgeClass: "bg-orange-600/15 text-orange-300 border-orange-600/30",
  },
  "class.monk": {
    img: "/assets/classes/monk.png",
    sub: "Way of Silence",
    badge: "Тишина · Тремор",
    badgeClass: "bg-cyan-600/15 text-cyan-300 border-cyan-600/30",
  },
  "class.paladin": {
    img: "/assets/classes/paladin.png",
    sub: "Knight of the Giants",
    badge: "Ликвор · Клятва",
    badgeClass: "bg-blue-600/15 text-blue-300 border-blue-600/30",
  },
  "class.ranger": {
    img: "/assets/classes/ranger.png",
    sub: "Deep Trail Stalker",
    badge: "Охотник троп",
    badgeClass: "bg-lime-600/15 text-lime-300 border-lime-600/30",
  },
  "class.rogue": {
    img: "/assets/classes/rogue.png",
    sub: "Liquor Smuggler",
    badge: "Контрабанда",
    badgeClass: "bg-stone-500/20 text-stone-300 border-stone-500/40",
  },
  "class.sorcerer": {
    img: "/assets/classes/sorcerer.png",
    sub: "Innate Conduit",
    badge: "Врождённый ликвор",
    badgeClass: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  },
  "class.warlock": {
    img: "/assets/classes/warlock.png",
    sub: "Deep Pactbinder",
    badge: "Договор глубин",
    badgeClass: "bg-purple-600/15 text-purple-300 border-purple-600/30",
  },
  "class.wizard": {
    img: "/assets/classes/wizard.png",
    sub: "Helmsmen Cryptographer",
    badge: "Формулы Кормчих",
    badgeClass: "bg-amber-500/15 text-amber-200 border-amber-500/30",
  },
};

function getClassArt(c: ClassOption): ClassArtMeta | null {
  if (CLASS_ART_MAP[c.id]) return CLASS_ART_MAP[c.id];
  const lower = c.name.toLowerCase();
  if (lower.includes("диагност")) return CLASS_ART_MAP["class.diagnost"];
  if (lower.includes("варвар")) return CLASS_ART_MAP["class.barbarian"];
  if (lower.includes("бард") || lower.includes("звонар")) return CLASS_ART_MAP["class.bard"];
  if (lower.includes("жрец") || lower.includes("церкв")) return CLASS_ART_MAP["class.cleric"];
  if (lower.includes("друид") || lower.includes("паразит")) return CLASS_ART_MAP["class.druid"];
  if (lower.includes("воин")) return CLASS_ART_MAP["class.fighter"];
  if (lower.includes("монах") || lower.includes("молчальн")) return CLASS_ART_MAP["class.monk"];
  if (lower.includes("паладин") || lower.includes("рыцар")) return CLASS_ART_MAP["class.paladin"];
  if (lower.includes("следопыт") || lower.includes("сталкер")) return CLASS_ART_MAP["class.ranger"];
  if (lower.includes("плут")) return CLASS_ART_MAP["class.rogue"];
  if (lower.includes("чародей")) return CLASS_ART_MAP["class.sorcerer"];
  if (lower.includes("колдун")) return CLASS_ART_MAP["class.warlock"];
  if (lower.includes("волшебник") || lower.includes("ликворовед")) return CLASS_ART_MAP["class.wizard"];
  return null;
}

function formatClassSaves(saves: string[]): string {
  if (!saves || saves.length === 0) return "";
  return saves.map((s) => ABILITY_ABBR[s] ?? ABILITY_RU[s] ?? s.toUpperCase()).join(", ");
}

interface ClassChoicesProps {
  items: ClassOption[];
  value: string;
  onPick: (id: string) => void;
}

export default function ClassChoices({ items, value, onPick }: ClassChoicesProps) {
  return (
    <div className="grid gap-3.5 md:grid-cols-2" role="radiogroup" aria-label="Выбор класса">
      {items.map((c) => {
        const on = c.id === value;
        const art = getClassArt(c);
        const saves = formatClassSaves(c.saving_throws);

        return (
          <button
            key={c.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onPick(c.id)}
            className={`group relative flex h-[175px] sm:h-[185px] w-full text-left rounded-[12px] border overflow-hidden transition-all duration-200 cursor-pointer ${
              on
                ? "border-accent bg-surface shadow-[0_4px_24px_rgba(201,138,75,0.24)] ring-1 ring-accent/40"
                : "border-line bg-surface/80 hover:border-accent/60 hover:bg-surface hover:-translate-y-0.5 hover:shadow-lg"
            }`}
          >
            {/* Текстовая колонка слева */}
            <div className="relative z-10 flex flex-1 flex-col justify-between p-3.5 sm:p-4 min-w-0">
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5">
                  {on && (
                    <span className="font-bold text-accent text-sm leading-none">✓</span>
                  )}
                  <span
                    className={`font-heading text-lg sm:text-xl font-bold leading-tight tracking-tight transition ${
                      on ? "text-accent" : "text-ink group-hover:text-accent"
                    }`}
                  >
                    {c.name}
                  </span>
                </div>

                {art?.sub && (
                  <span className="font-serif italic text-xs text-muted/90 mt-0.5 tracking-wide">
                    {art.sub}
                  </span>
                )}

                {c.description && (
                  <p className="mt-1.5 text-xs text-muted/80 line-clamp-2 leading-relaxed">
                    {c.description}
                  </p>
                )}
              </div>

              {/* Нижняя строчка: бейдж роли и механика (кость хитов + спасброски) */}
              <div className="flex items-center justify-between gap-2 mt-2 pt-1 border-t border-line/40">
                {art?.badge ? (
                  <span
                    className={`font-mono text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded border ${art.badgeClass}`}
                  >
                    {art.badge}
                  </span>
                ) : (
                  <span className="font-mono text-[10px] text-muted">
                    {c.hit_die ? `d${c.hit_die}` : "—"}
                  </span>
                )}

                <div className="flex items-center gap-2 font-mono text-[10.5px] text-muted-hi font-medium tracking-tight truncate">
                  {c.hit_die && (
                    <span className="px-1.5 py-0.5 rounded bg-raised/80 border border-line/60 text-ink/90 font-semibold">
                      d{c.hit_die}
                    </span>
                  )}
                  {saves && (
                    <span className="truncate" title={`Спасброски: ${saves}`}>
                      спас: {saves}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Иллюстрированный портрет справа с градиентной виньеткой */}
            {art?.img && (
              <div className="relative w-36 sm:w-44 h-full shrink-0 overflow-hidden pointer-events-none select-none">
                {/* Мягкая градиентная маска */}
                <div className="absolute inset-0 z-1 bg-gradient-to-r from-surface via-surface/85 to-transparent to-75%" />
                <img
                  src={art.img}
                  alt={c.name}
                  className="w-full h-full object-cover object-top filter brightness-[0.92] contrast-[1.05] group-hover:brightness-100 group-hover:scale-105 transition-all duration-300"
                  loading="lazy"
                />
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
