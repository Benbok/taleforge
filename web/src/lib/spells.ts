// Заклинания в интерфейсе: карточки с сервера (русские подписи уже готовы) и подсчёт выбора.
// Правила и числа — на сервере (app/rules/dnd5e/spells.py), здесь только группировка и подсказки.

/** Карточка заклинания, как её отдаёт сервер. */
export interface SpellCard {
  id: string;
  name: string;
  level: number;
  school: string;
  casting_time: string;
  /** Творится действием, бонусным действием или реакцией — значит, успеть можно и в бою. */
  combat: boolean;
  range: string;
  components: string[];
  material?: string | null;
  duration: string;
  concentration: boolean;
  ritual: boolean;
  description: string;
  higher_levels?: string;
  /** Как заклинание выглядит в мире кампании. */
  flavor?: string;
  attack?: "melee" | "ranged" | null;
  save?: string | null;
  area?: { shape: string; size_ft: number } | null;
  /** Кого выбирать целью: enemy — врага, ally — союзника или себя, self — никого, area — область, any — кого угодно. */
  targets: "enemy" | "ally" | "self" | "area" | "any";
  /** В книге героя: готово ли к сотворению (заговоры и известные — всегда). */
  prepared?: boolean;
}

/** Заклинания класса в конструкторе: сколько выбрать на стартовом уровне и из чего. */
export interface ClassSpells {
  ability: string;
  mode: "known" | "prepared" | "spellbook";
  cantrips: number;
  /** Сколько известных заклинаний (или заклинаний в книге волшебника). */
  known: number | null;
  /** Как считается число подготовленных — словами; само число считает живой лист. */
  prepared_rule: string | null;
  top_level: number;
  slots: number[];
  pact_slots: number;
  pact_level: number;
  /** Откуда сила в мире кампании. */
  source: string;
  spells: SpellCard[];
}

/** Книга заклинаний героя в игре. */
export interface Spellbook {
  ability: string;
  mode: "known" | "prepared" | "spellbook";
  mode_ru: string;
  save_dc: number;
  attack: number;
  cantrips: number;
  known: number | null;
  prepared: number | null;
  slots: number[];
  slots_left: Record<string, number>;
  pact_slots: number;
  pact_level: number;
  pact_left: number;
  top_level: number;
  ritual: string | null;
  source: string;
  concentration: { spell_id: string; name: string } | null;
  can_prepare: boolean;
  spells: SpellCard[];
  room: { cantrips: number; spells: number; prepared: number };
}

export const LEVEL_RU = (n: number) => (n === 0 ? "Заговоры" : `${n}-й круг`);
export const COMPONENT_RU: Record<string, string> = { V: "словесный", S: "жестовый", M: "материальный" };
export const MODE_HINT: Record<string, string> = {
  known: "Вы знаете немного заклинаний и творите любое из них, пока есть ячейки.",
  prepared:
    "Вам открыт весь список класса. Каждый день после продолжительного отдыха вы готовите часть из него — творить можно только подготовленные.",
  spellbook:
    "Заклинания записаны в книгу. После продолжительного отдыха вы готовите часть из книги; ритуалы из книги можно творить и неподготовленными.",
};

export function byLevel(list: SpellCard[]): [number, SpellCard[]][] {
  const out = new Map<number, SpellCard[]>();
  for (const s of list) out.set(s.level, [...(out.get(s.level) ?? []), s]);
  return [...out.entries()].sort((a, b) => a[0] - b[0]);
}

/** Строка свойств заклинания под именем: круг и школа, время, дистанция. */
export function spellMeta(s: SpellCard): string {
  const head = s.level === 0 ? `заговор, ${s.school}` : `${s.level}-й круг, ${s.school}`;
  return [head, s.casting_time, s.range].join(" · ");
}

export function toggleIn(list: string[], id: string, max: number): string[] {
  if (list.includes(id)) return list.filter((x) => x !== id);
  if (list.length >= max) return list;
  return [...list, id];
}
