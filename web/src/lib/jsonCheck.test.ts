import { expect, it } from "vitest";
import { checkAgainstSchema, parseLooseJson } from "./jsonCheck";

it("достаёт JSON из ответа модели с обёрткой и текстом вокруг", () => {
  expect(parseLooseJson('Конечно!\n```json\n{"a": 1}\n```\nУдачи').value).toEqual({ a: 1 });
  expect(parseLooseJson("просто текст").error).toContain("не найден");
  expect(parseLooseJson('{"a": }').error).toContain("не разобран");
  expect(parseLooseJson("").value).toBeNull();
});

it("называет путь к каждому расхождению", () => {
  const schema = {
    type: "object",
    required: ["title", "npcs"],
    properties: {
      title: { type: "string", maxLength: 5 },
      npcs: { type: "array", minItems: 2, items: { type: "object", required: ["id", "name"], properties: { name: { type: "string" } } } },
      mode: { type: "string", enum: ["a", "b"] },
    },
  };
  const issues = checkAgainstSchema({ title: "слишком длинно", npcs: [{ id: "x", name: 3 }], mode: "c" }, schema);
  const paths = issues.map((i) => `${i.path}: ${i.message}`);
  expect(paths).toContain("title: не длиннее 5 символов (сейчас 14)");
  expect(paths).toContain("npcs: нужно не меньше 2 (сейчас 1)");
  expect(paths).toContain("npcs[0].name: нужен строка");
  expect(paths).toContain("mode: одно из: a, b");
  expect(checkAgainstSchema({}, schema).map((i) => i.path)).toEqual(["title", "npcs"]);
});
