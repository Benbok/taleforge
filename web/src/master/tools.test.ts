import { describe, expect, it } from "vitest";
import type { Envelope } from "../lib/types";
import { buildArgs, initialValues, problems, resolveToolResult, type ToolField, type ToolSpec } from "./tools";

const f = (x: Partial<ToolField> & { name: string }): ToolField => ({
  type: "string",
  many: false,
  required: false,
  nullable: false,
  default: null,
  description: "",
  options: null,
  min: null,
  max: null,
  max_length: null,
  ...x,
});

const spawn: ToolSpec = {
  name: "spawn_entity",
  description: "",
  group: "scene",
  mutating: true,
  fields: [
    f({ name: "creature_template_id", required: true, options: ["creature.goblin"] }),
    f({ name: "name", required: true }),
    f({ name: "count", type: "integer", default: 1, min: 1, max: 12 }),
    f({ name: "description", default: "" }),
  ],
};

const rest: ToolSpec = {
  name: "rest",
  description: "",
  group: "players",
  mutating: true,
  fields: [f({ name: "character_ids", many: true, required: true, options: ["ch_1"] }), f({ name: "fled", type: "boolean", nullable: true })],
};

describe("формы инструментов мастера", () => {
  it("начальные значения из схемы, подстановка поверх", () => {
    const v = initialValues(spawn, { creature_template_id: "creature.goblin" });
    expect(v).toEqual({ creature_template_id: "creature.goblin", name: "", count: "1", description: "" });
    expect(initialValues(rest)).toEqual({ character_ids: [], fled: "" });
  });

  it("причины по-русски: пустое обязательное и число вне границ", () => {
    expect(problems(spawn, initialValues(spawn))).toEqual(["заполните «Шаблон существа»", "заполните «Имя»"]);
    expect(problems(spawn, { ...initialValues(spawn), creature_template_id: "x", name: "Гоблин", count: "20" })).toEqual([
      "«Сколько»: не больше 12",
    ]);
    expect(problems(rest, { character_ids: [], fled: "" })).toEqual(["заполните «Персонажи»"]);
  });

  it("аргументы: числа числами, пустые необязательные не отправляются, «не менять» не отправляется", () => {
    expect(buildArgs(spawn, { creature_template_id: "creature.goblin", name: " Гоблин ", count: "3", description: "" })).toEqual({
      creature_template_id: "creature.goblin",
      name: "Гоблин",
      count: 3,
    });
    expect(buildArgs(rest, { character_ids: ["ch_1"], fled: "" })).toEqual({ character_ids: ["ch_1"] });
    expect(buildArgs(rest, { character_ids: ["ch_1"], fled: "false" })).toEqual({ character_ids: ["ch_1"], fled: false });
  });

  it("чужие ответы и другие события не перехватываются", () => {
    expect(resolveToolResult({ type: "master.tool.result", campaign_id: "c", seq: null, payload: { request_id: "nope", ok: true } })).toBe(false);
    expect(resolveToolResult({ type: "message.new", campaign_id: "c", seq: 1, payload: {} } as unknown as Envelope)).toBe(false);
  });
});
