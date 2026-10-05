// Окно сотворения заклинания (просьба Arty 2026-10-05): игрок шаг за шагом выбирает цель, ячейку и как именно,
// а не отправляет одно название, оставляя «что, куда и на кого» мастеру. Здесь — чистая логика шагов и подсказок,
// числа и окончательную проверку дальности делает сервер.
import type { SpellCard } from "../lib/spells";

export type Step = "target" | "slot" | "confirm";

export interface Candidate {
  id: string;
  name: string;
  group: "foe" | "other" | "ally";
  /** Зона относительно центра отряда; у героя — null (стоит в строю). */
  zone: string | null;
}

export const ZONE_FT: Record<string, number> = { melee: 5, near: 30, far: 120 };
export const ZONE_RU: Record<string, string> = { melee: "вплотную", near: "близко", far: "далеко" };

/** Дальность заклинания в футах из русской подписи сервера; null — без ограничения или особая. */
export function rangeFt(s: Pick<SpellCard, "range" | "area">): number | null {
  const r = s.range ?? "";
  if (r === "касание") return 5;
  if (r.startsWith("на себя")) return s.area?.size_ft ?? null;
  const m = /^(\d+) фт$/.exec(r);
  return m ? Number(m[1]) : null;
}

/** Площадное заклинание: игрок отмечает всех, кого накрывает область. */
export function multi(s: Pick<SpellCard, "targets">): boolean {
  return s.targets === "area";
}

/** Кого можно выбрать целью: враги первыми, потом прочие существа, потом союзники. */
export function candidates(
  s: Pick<SpellCard, "targets">,
  creatures: { id: string; name: string; zone: string; hostile: boolean }[],
  allies: { id: string; name: string }[],
): Candidate[] {
  const foes = creatures.map((c) => ({ id: c.id, name: c.name, group: c.hostile ? "foe" : "other", zone: c.zone }) as Candidate);
  const sorted = [...foes.filter((f) => f.group === "foe"), ...foes.filter((f) => f.group !== "foe")];
  const friends = allies.map((a) => ({ id: a.id, name: a.name, group: "ally", zone: null }) as Candidate);
  if (s.targets === "enemy") return sorted;
  if (s.targets === "area") return [...sorted, ...friends];
  if (s.targets === "ally") return friends;
  if (s.targets === "any") return [...friends, ...sorted];
  return [];
}

/** Шаги окна: сначала цель словами игрока (у заклинаний на себя — что именно происходит), ячейка — когда есть выбор. */
export function steps(slotChoices: number, canRitual: boolean): Step[] {
  return ["target", ...(slotChoices > 1 || canRitual ? (["slot"] as Step[]) : []), "confirm"];
}

/** Что мешает перейти дальше с шага цели; null — можно. Цель словами годится всегда: что нет в сцене, заведёт мастер. */
export function targetProblem(s: Pick<SpellCard, "targets" | "name">, chosen: string[], described: string): string | null {
  if (s.targets === "self" || chosen.length || described.trim()) return null;
  if (s.targets === "enemy") return `Опишите, в кого направить «${s.name}», или выберите из сцены.`;
  if (s.targets === "area") return "Опишите, кого или что накроет область, или отметьте из сцены.";
  return null; // союзное и «на кого угодно» без цели — на себя
}

/** Предупреждения по дальности: зона — грубая оценка, точное расстояние сервер считает по схеме. */
export function rangeWarnings(s: Pick<SpellCard, "range" | "area">, chosen: Candidate[]): string[] {
  const ft = rangeFt(s);
  if (ft == null) return [];
  return chosen
    .filter((c) => c.zone && (ZONE_FT[c.zone] ?? 0) > ft)
    .map((c) => `${c.name} ${ZONE_RU[c.zone!] ?? c.zone}, а дальность ${s.range}: заклинание может не достать.`);
}

/** Строка в чат: что, в кого, какой ячейкой и как. У заклинания на себя описание идёт после точки. */
export function castLine(
  spell: string,
  targets: string[],
  slot: number | null,
  ritual: boolean,
  manner: string,
  area: boolean,
): string {
  const parts = [`Творю «${spell}»`];
  if (targets.length) parts.push(area ? `накрывая: ${targets.join(", ")}` : `на ${targets.join(", ")}`);
  if (ritual) parts.push("ритуалом");
  else if (slot) parts.push(`ячейкой ${slot}-го круга`);
  const how = manner.trim();
  return how ? `${parts.join(" ")}. ${how[0].toUpperCase()}${how.slice(1)}` : parts.join(" ");
}
