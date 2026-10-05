import { describe, expect, it } from "vitest";
import { candidates, castLine, rangeFt, rangeWarnings, steps, targetProblem } from "./castPlan";

const creatures = [
  { id: "en_1", name: "Крыса", zone: "near", hostile: false },
  { id: "en_2", name: "Гоблин", zone: "far", hostile: true },
];
const allies = [{ id: "ch_1", name: "Ильва (вы)" }];

describe("окно сотворения", () => {
  it("дальность читается из подписи сервера", () => {
    expect(rangeFt({ range: "касание", area: null })).toBe(5);
    expect(rangeFt({ range: "120 фт", area: null })).toBe(120);
    expect(rangeFt({ range: "на себя (конус 15 фт)", area: { shape: "cone", size_ft: 15 } })).toBe(15);
    expect(rangeFt({ range: "в пределах видимости", area: null })).toBeNull();
  });

  it("враги — первыми; у союзного заклинания — только отряд; у площадного — все", () => {
    expect(candidates({ targets: "enemy" }, creatures, allies).map((c) => c.id)).toEqual(["en_2", "en_1"]);
    expect(candidates({ targets: "ally" }, creatures, allies).map((c) => c.id)).toEqual(["ch_1"]);
    expect(candidates({ targets: "area" }, creatures, allies)).toHaveLength(3);
  });

  it("шаги: цель всегда первой, ячейка — только при выборе", () => {
    expect(steps(1, false)).toEqual(["target", "confirm"]);
    expect(steps(2, false)).toEqual(["target", "slot", "confirm"]);
    expect(steps(0, true)).toEqual(["target", "slot", "confirm"]);
  });

  it("цель словами или из сцены; у заклинания на себя цель не нужна", () => {
    expect(targetProblem({ targets: "enemy", name: "Огненный снаряд" }, [], " ")).toContain("Огненный снаряд");
    expect(targetProblem({ targets: "area", name: "x" }, [], "")).toContain("область");
    expect(targetProblem({ targets: "enemy", name: "x" }, ["en_2"], "")).toBeNull();
    expect(targetProblem({ targets: "enemy", name: "x" }, [], "факел на стене")).toBeNull();
    expect(targetProblem({ targets: "self", name: "Мимикрия" }, [], "")).toBeNull();
    expect(targetProblem({ targets: "ally", name: "x" }, [], "")).toBeNull();
  });

  it("предупреждает, когда цель, похоже, дальше дальности", () => {
    const [far] = candidates({ targets: "enemy" }, creatures, allies);
    expect(rangeWarnings({ range: "60 фт", area: null }, [far])[0]).toContain("Гоблин далеко");
    expect(rangeWarnings({ range: "120 фт", area: null }, [far])).toEqual([]);
  });

  it("строка в чат: цели, ячейка, как именно", () => {
    expect(castLine("Огненный снаряд", ["Гоблин"], null, false, "", false)).toBe("Творю «Огненный снаряд» на Гоблин");
    expect(castLine("Огненные ладони", ["Гоблин", "Крыса"], 2, false, "веером на север", true)).toBe(
      "Творю «Огненные ладони» накрывая: Гоблин, Крыса ячейкой 2-го круга. Веером на север",
    );
  });
});
