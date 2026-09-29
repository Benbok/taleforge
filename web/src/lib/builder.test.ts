import { describe, expect, it } from "vitest";
import {
  builderUrls,
  draftFrom,
  emptyDraft,
  equipFor,
  groupOptions,
  pointsSpent,
  poolLeft,
  splitPicks,
  steps,
  toBody,
  weaponSlots,
  withMethod,
  type BuilderOptions,
} from "./builder";

const opts: BuilderOptions = {
  ability_methods: ["standard_array", "point_buy", "roll"],
  standard_array: [15, 14, 13, 12, 10, 8],
  point_buy: { budget: 27, cost: { "8": 0, "9": 1, "10": 2, "11": 3, "12": 4, "13": 5, "14": 7, "15": 9 } },
  start_level: 1,
  classes: [
    {
      id: "fighter",
      name: "Воин",
      description: "",
      hit_die: 10,
      saving_throws: ["str", "con"],
      skills_choose: { count: 2, from: ["athletics", "perception", "survival"] },
      equipment_fixed: [],
      equipment_choices: [
        [[{ item: "chain_mail", name: "Кольчуга" }], [{ item: "leather", name: "Кожаный" }, { item: "longbow", name: "Лук" }]],
        [[{ any: "martial", qty: 2 }], [{ any: "martial" }, { item: "shield", name: "Щит" }]],
      ],
    },
  ],
  origins: [],
  weapons: {
    longsword: { name: "Длинный меч", group: "martial_melee" },
    battleaxe: { name: "Боевой топор", group: "martial_melee" },
    dagger: { name: "Кинжал", group: "simple_melee" },
  },
};

describe("конструктор героя", () => {
  it("раскладывает стандартный набор по разу", () => {
    const ab = { str: 15, dex: 14, con: null, int: null, wis: null, cha: null };
    expect(poolLeft(opts.standard_array, ab, "con")).toEqual([13, 12, 10, 8]);
    expect(poolLeft(opts.standard_array, ab, "str")).toEqual([15, 13, 12, 10, 8]);
  });

  it("считает потраченные очки, пустое — как 8", () => {
    expect(pointsSpent({ str: 15, dex: 14, con: 13, int: 8, wis: 8, cha: null }, opts.point_buy.cost)).toBe(21);
  });

  it("смена способа сбрасывает числа, покупка очков начинает с 8", () => {
    const d = { ...emptyDraft(opts), abilities: { str: 15, dex: 14, con: 13, int: 12, wis: 10, cha: 8 } };
    expect(Object.values(withMethod(d, "point_buy").abilities)).toEqual([8, 8, 8, 8, 8, 8]);
    expect(Object.values(withMethod(d, "roll").abilities).every((v) => v === null)).toBe(true);
  });

  it("снаряжение по умолчанию и оружие на выбор", () => {
    const eq = equipFor(opts.classes[0], [], opts);
    expect(eq).toEqual([
      { choice: 0, option: 0, items: [] },
      { choice: 1, option: 0, items: ["battleaxe", "battleaxe"] },
    ]);
    expect(weaponSlots([{ any: "martial", qty: 2 }], ["longsword"], opts)).toEqual(["longsword", "battleaxe"]);
    // прежний выбор сохраняется, если такой вариант ещё есть
    expect(equipFor(opts.classes[0], [{ choice: 1, option: 1, items: ["longsword"] }], opts)[1]).toEqual({
      choice: 1,
      option: 1,
      items: ["longsword"],
    });
  });

  it("тело запроса без пустых полей и с бросками", () => {
    const d = { ...emptyDraft(opts), name: "Бран", abilities: { ...emptyDraft(opts).abilities, str: 15 } };
    const body = toBody(d, [16, 12]);
    expect(body).not.toHaveProperty("class_id");
    expect(body.abilities).toEqual({ str: 15 });
    expect(body.ability_rolls).toEqual([16, 12]);
  });

  it("черновик из сохранённого героя", () => {
    const d = draftFrom(
      { id: "h", name: "Бран", sheet: { class_id: "fighter", ability_method: "point_buy", abilities: { str: 15 }, skills: ["athletics"] } },
      opts,
    );
    expect(d.class_id).toBe("fighter");
    expect(d.ability_method).toBe("point_buy");
    expect(d.abilities.str).toBe(15);
    expect(d.abilities.dex).toBeNull();
    const st = steps(d, opts);
    expect(st.find((s) => s.id === "name")!.done).toBe(true);
    expect(st.find((s) => s.id === "skills")!.done).toBe(false);
  });

  it("адреса по режимам", () => {
    expect(builderUrls("library", undefined, undefined).save).toBe("/api/me/characters");
    expect(builderUrls("campaign", "c1", "h1").roll).toBe("/api/campaigns/c1/characters/h1/roll-abilities");
    expect(builderUrls("premade", "c1", "p1")).toMatchObject({ save: "/api/campaigns/c1/premades/p1", roll: null });
    // героя ИИ-игрока владелец собирает за его место
    expect(builderUrls("campaign", "c1", "h1", "s2")).toMatchObject({
      options: "/api/campaigns/c1/character-options?as_seat=s2",
      save: "/api/campaigns/c1/characters/h1?as_seat=s2",
      submit: "/api/campaigns/c1/characters/h1/submit?as_seat=s2",
    });
  });

  it("прибавки происхождения по группам: Кровник", () => {
    const krovnik = {
      id: "origin.krovnik",
      name: "Кровник",
      description: "",
      ability_bonuses: {},
      ability_groups: [
        { count: 1, bonus: 2, from: ["str", "con"], distinct_from_prior: false },
        { count: 1, bonus: 1, from: ["str", "dex", "con", "int", "wis", "cha"], distinct_from_prior: true },
      ],
      speed: 30,
      features: [],
    };
    expect(splitPicks(["con", "str"], krovnik)).toEqual([["con"], ["str"]]);
    expect(groupOptions(krovnik, [["con"], []], 1)).not.toContain("con");
  });
});
