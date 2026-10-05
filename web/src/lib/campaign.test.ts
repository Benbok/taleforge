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
      leveling: "xp",
    });
    expect(createBody({ ...EMPTY_DRAFT, name: "Туман", leveling: "milestone" }).leveling).toBe("milestone");
    expect(body).not.toHaveProperty("players");
  });

  it("мастер — сам владелец: ни персоны, ни места игрока", () => {
    const body = createBody({ ...EMPTY_DRAFT, name: "Х", master: "owner", persona: "my:p1", players: 3 });
    expect(body).toMatchObject({ master: { type: "owner" }, owner_plays: false, players: 3 });
  });

  it("ИИ-мастер с пресетом, стилем и анкетой характера", () => {
    const body = createBody({
      ...EMPTY_DRAFT,
      name: "Поход",
      master: "mp1",
      master_preset_id: "preset-123",
      master_style: "говорит тихо и загадочно",
      master_character: {
        text: "Строгий судья",
        fields: { tricks: "паузы перед боем", never: "не врёт о бросках" },
        core: ["never"],
      },
    });
    expect(body.master).toEqual({
      type: "agent",
      model_profile_id: "mp1",
      persona_preset: "storyteller",
      preset_id: "preset-123",
      style: "говорит тихо и загадочно",
      character: {
        text: "Строгий судья",
        fields: { tricks: "паузы перед боем", never: "не врёт о бросках" },
        core: ["never"],
      },
    });
  });

  it("готовое приключение: свой пакет и рост по вехам книги", () => {
    const d = { ...EMPTY_DRAFT, name: "Склеп", source: "module" as const, pack_id: "echo", leveling: "xp" as const };
    expect(stepProblems(d, 0)).toEqual(["Выберите приключение"]);
    const body = createBody({ ...d, module_id: "mod1", module_hook: "board" });
    expect(body).toMatchObject({ module_id: "mod1", module_hook: "board", pack_id: null, leveling: "milestone" });
    // выбрали приключение, а потом вернулись к своему сюжету: модуль в запрос не уходит
    expect(createBody({ ...d, source: "plot", module_id: "mod1" })).not.toHaveProperty("module_id");
  });

  it("мелочи", () => {
    expect(personaBody("my:p1")).toEqual({ persona_id: "p1" });
    expect(personaBody("")).toEqual({});
    expect(splitThemes("a,b , ,c")).toEqual(["a", "b", "c"]);
    expect(stepProblems(EMPTY_DRAFT, 0)).toEqual(["Назовите кампанию"]);
    expect(stepProblems(EMPTY_DRAFT, 1)).toEqual([]);
  });
});
