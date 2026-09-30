import { describe, expect, it } from "vitest";
import { emptyDraft, spellNeed, steps, type BuilderOptions, type ClassOption, type Preview } from "./builder";
import { byLevel, spellMeta, toggleIn, type ClassSpells, type SpellCard } from "./spells";

const card = (id: string, level: number): SpellCard => ({
  id,
  name: id,
  level,
  school: "воплощение",
  casting_time: "1 действие",
  combat: true,
  range: "120 фт",
  components: ["V", "S"],
  duration: "мгновенно",
  concentration: false,
  ritual: false,
  description: "",
  targets: "enemy",
});

const wizardSpells: ClassSpells = {
  ability: "int",
  mode: "spellbook",
  cantrips: 3,
  known: 6,
  prepared_rule: "модификатор Интеллекта + уровень",
  top_level: 1,
  slots: [2, 0, 0, 0, 0, 0, 0, 0, 0],
  pact_slots: 0,
  pact_level: 0,
  source: "",
  spells: [card("bolt", 0), card("missile", 1)],
};

const wizard: ClassOption = {
  id: "wizard",
  name: "Волшебник",
  description: "",
  hit_die: 6,
  saving_throws: ["int", "wis"],
  spells: wizardSpells,
  skills_choose: { count: 0 },
  equipment_fixed: [],
  equipment_choices: [],
};

const opts: BuilderOptions = {
  ability_methods: ["standard_array"],
  standard_array: [15, 14, 13, 12, 10, 8],
  point_buy: { budget: 27, cost: {} },
  start_level: 1,
  classes: [wizard],
  origins: [],
  weapons: {},
};

describe("заклинания", () => {
  it("группирует по кругам: заговоры первыми", () => {
    const g = byLevel([card("b", 1), card("a", 0), card("c", 1)]);
    expect(g.map(([l, xs]) => [l, xs.map((x) => x.id)])).toEqual([
      [0, ["a"]],
      [1, ["b", "c"]],
    ]);
    expect(spellMeta(card("a", 0))).toBe("заговор, воплощение · 1 действие · 120 фт");
  });

  it("не даёт выбрать больше положенного, повторный выбор убирает", () => {
    expect(toggleIn(["a"], "b", 1)).toEqual(["a"]);
    expect(toggleIn(["a"], "a", 1)).toEqual([]);
    expect(toggleIn([], "a", 1)).toEqual(["a"]);
  });

  it("шаг заклинаний появляется у заклинателя и готов, когда всё выбрано", () => {
    const preview = { derived: { spellcasting: { needs: { cantrips: 3, spells: 6, prepared: 4 } } } } as unknown as Preview;
    expect(spellNeed(wizard, preview)).toEqual({ cantrips: 3, spells: 6, prepared: 4 });
    // пока характеристики не разложены, число подготовленных неизвестно
    expect(spellNeed(wizard, null)?.prepared).toBeNull();
    const d = { ...emptyDraft(opts), class_id: "wizard" };
    const step = () => steps(d, opts, preview).find((s) => s.id === "spells");
    expect(step()?.done).toBe(false);
    Object.assign(d, { cantrips: ["a", "b", "c"], spells: ["1", "2", "3", "4", "5", "6"], prepared: ["1", "2", "3", "4"] });
    expect(step()?.done).toBe(true);
    expect(steps({ ...d, class_id: "" }, opts, preview).some((s) => s.id === "spells")).toBe(false);
  });
});
