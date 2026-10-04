import { describe, expect, it } from "vitest";
import { ABILITIES, SKILLS } from "./hero";
import {
  ABILITY_DETAILS,
  getAbilityDetail,
  getMasteryDetail,
  getSkillDetail,
  MASTERY_DETAIL,
  SKILL_DETAILS,
} from "./statDetails";

describe("statDetails", () => {
  it("contains all 6 core abilities", () => {
    expect(Object.keys(ABILITY_DETAILS).length).toBe(6);
    for (const a of ABILITIES) {
      const detail = getAbilityDetail(a);
      expect(detail).toBeDefined();
      expect(detail?.name).toBeTruthy();
      expect(detail?.abbr).toBeTruthy();
      expect(detail?.description).toBeTruthy();
      expect(detail?.affects.length).toBeGreaterThan(0);
    }
  });

  it("contains all 18 skills and matches hero.ts skills mapping", () => {
    expect(Object.keys(SKILL_DETAILS).length).toBe(18);
    for (const [id, ru, ability] of SKILLS) {
      const detail = getSkillDetail(id);
      expect(detail).toBeDefined();
      expect(detail?.name).toBe(ru);
      expect(detail?.ability).toBe(ability);
      expect(detail?.description).toBeTruthy();
      expect(detail?.examples.length).toBeGreaterThan(0);
    }
  });

  it("provides detailed mastery explanation", () => {
    expect(MASTERY_DETAIL.id).toBe("proficiency_bonus");
    const mastery = getMasteryDetail();
    expect(mastery).toBeDefined();
    expect(mastery.name).toBe("Бонус мастерства");
    expect(mastery.howItWorks.length).toBeGreaterThanOrEqual(4);
  });
});
