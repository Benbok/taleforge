import { beforeEach, describe, expect, it } from "vitest";
import {
  cleanBrief,
  createBody,
  EMPTY_DRAFT,
  latestAdventures,
  launchBody,
  loadDraft,
  personaBody,
  saveDraft,
  splitThemes,
  stepProblems,
} from "./campaign";

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

  it("приключение автора: настройки стола уходят в запуск версии, пустая афиша остаётся авторской", () => {
    const d = {
      ...EMPTY_DRAFT,
      name: " Вечер ",
      source: "module" as const,
      adventure_id: "av_2",
      players: 3,
      master: "mp1",
      persona: "pre:chronicler" as const,
      review: "auto" as const,
      excluded: "пауки",
      leveling: "milestone" as const,
    };
    expect(stepProblems(d, 0)).toEqual([]);
    expect(launchBody(d)).toEqual({
      name: "Вечер",
      players: 3,
      master: { type: "agent", model_profile_id: "mp1", persona_preset: "chronicler" },
      owner_plays: true,
      excluded_themes: ["пауки"],
      creation_rules: { review: "auto" },
      leveling: "milestone",
      public_intro: null,
    });
    expect(launchBody({ ...d, players: null, public_intro: " Афиша " })).toMatchObject({ players: 4, public_intro: "Афиша" });
    expect(stepProblems({ ...d, adventure_id: "" }, 0)).toEqual(["Выберите приключение"]);
  });

  it("в списке по одному приключению на проект, но выбранная старая версия не пропадает", () => {
    const v = (id: string, project_id: string, version: number) => ({
      id,
      project_id,
      version,
      source_revision: 1,
      public_summary: {},
      published_at: "2026-10-19T10:00:00Z",
    });
    const all = [v("av_3", "ap_1", 3), v("av_9", "ap_2", 1), v("av_2", "ap_1", 2)];
    expect(latestAdventures(all, "").map((x) => x.id)).toEqual(["av_3", "av_9"]);
    expect(latestAdventures(all, "av_2").map((x) => x.id)).toEqual(["av_3", "av_9", "av_2"]);
  });

  it("мелочи", () => {
    expect(personaBody("my:p1")).toEqual({ persona_id: "p1" });
    expect(personaBody("")).toEqual({});
    expect(splitThemes("a,b , ,c")).toEqual(["a", "b", "c"]);
    expect(stepProblems(EMPTY_DRAFT, 0)).toEqual(["Назовите кампанию"]);
    expect(stepProblems(EMPTY_DRAFT, 1)).toEqual([]);
  });
});
