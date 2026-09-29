import { beforeEach, describe, expect, it } from "vitest";
import { cleanBrief, createBody, EMPTY_DRAFT, loadDraft, personaBody, saveDraft, splitThemes, stepProblems } from "./campaign";

describe("создание кампании", () => {
  beforeEach(() => localStorage.clear());

  it("черновик живёт в браузере и принадлежит своему пользователю", () => {
    saveDraft("u1", { ...EMPTY_DRAFT, name: "Туман", step: 2 });
    expect(loadDraft("u1")).toMatchObject({ name: "Туман", step: 2, difficulty: "normal" });
    expect(loadDraft("u2")).toBeNull();
    saveDraft("u1", null);
    expect(loadDraft("u1")).toBeNull();
  });

  it("анкета без пустого и без средних долей", () => {
    expect(cleanBrief({ length: "", pillars: { combat: "mid", social: "high" }, emotions: [], wishes: "  " })).toEqual({
      pillars: { social: "high" },
    });
  });

  it("ИИ-мастер с персоной и владелец-игрок", () => {
    const body = createBody({ ...EMPTY_DRAFT, name: " Туман ", master: "mp1", persona: "pre:chronicler", excluded: "пытки, , пауки" });
    expect(body).toMatchObject({
      name: "Туман",
      pack_id: null,
      master: { type: "agent", model_profile_id: "mp1", persona_preset: "chronicler" },
      excluded_themes: ["пытки", "пауки"],
      owner_plays: true,
      creation_rules: { review: "master" },
    });
    expect(body).not.toHaveProperty("players");
  });

  it("мастер — сам владелец: ни персоны, ни места игрока", () => {
    const body = createBody({ ...EMPTY_DRAFT, name: "Х", master: "owner", persona: "my:p1", players: 3 });
    expect(body).toMatchObject({ master: { type: "owner" }, owner_plays: false, players: 3 });
  });

  it("мелочи", () => {
    expect(personaBody("my:p1")).toEqual({ persona_id: "p1" });
    expect(personaBody("")).toEqual({});
    expect(splitThemes("a,b , ,c")).toEqual(["a", "b", "c"]);
    expect(stepProblems(EMPTY_DRAFT, 0)).toEqual(["Назовите кампанию"]);
    expect(stepProblems(EMPTY_DRAFT, 1)).toEqual([]);
  });
});
