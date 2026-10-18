// Проверка вставленного JSON по той же схеме, что получает модель: до отправки видно, чего не хватает и где.
// Поддержано подмножество JSON Schema, которое используют схемы этапов: type, properties, required, items,
// minItems/maxItems, maxLength, enum.

export interface SchemaIssue {
  path: string;
  message: string;
}

type Schema = {
  type?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  minItems?: number;
  maxItems?: number;
  maxLength?: number;
  enum?: unknown[];
  anyOf?: Schema[];
};

const TYPE_RU: Record<string, string> = { string: "строка", array: "список", object: "объект", boolean: "да/нет", integer: "целое число", number: "число" };

function typeOf(v: unknown): string {
  if (Array.isArray(v)) return "array";
  if (v === null) return "null";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

function fits(expected: string, v: unknown): boolean {
  const actual = typeOf(v);
  return actual === expected || (expected === "number" && actual === "integer");
}

export function checkAgainstSchema(value: unknown, schema: Schema, path = ""): SchemaIssue[] {
  const at = path || "(корень)";
  if (schema.anyOf) {
    const variants = schema.anyOf.map((s) => checkAgainstSchema(value, s, path));
    return variants.find((v) => v.length === 0) ?? variants[0] ?? [];
  }
  if (schema.type && !fits(schema.type, value)) {
    return [{ path: at, message: `нужен ${TYPE_RU[schema.type] ?? schema.type}` }];
  }
  const out: SchemaIssue[] = [];
  if (schema.enum && !schema.enum.includes(value)) out.push({ path: at, message: `одно из: ${schema.enum.join(", ")}` });
  if (typeof value === "string" && schema.maxLength && value.length > schema.maxLength) {
    out.push({ path: at, message: `не длиннее ${schema.maxLength} символов (сейчас ${value.length})` });
  }
  if (Array.isArray(value)) {
    if (schema.minItems && value.length < schema.minItems) out.push({ path: at, message: `нужно не меньше ${schema.minItems} (сейчас ${value.length})` });
    if (schema.maxItems && value.length > schema.maxItems) out.push({ path: at, message: `не больше ${schema.maxItems} (сейчас ${value.length})` });
    if (schema.items) value.forEach((item, i) => out.push(...checkAgainstSchema(item, schema.items!, `${path}[${i}]`)));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (obj[key] === undefined || obj[key] === null || obj[key] === "") out.push({ path: path ? `${path}.${key}` : key, message: "не заполнено" });
    }
    for (const [key, sub] of Object.entries(schema.properties ?? {})) {
      if (obj[key] !== undefined && obj[key] !== null) out.push(...checkAgainstSchema(obj[key], sub, path ? `${path}.${key}` : key));
    }
  }
  return out;
}

/** JSON из ответа модели: снимает обёртку ```json и находит объект, даже если вокруг остался текст. */
export function parseLooseJson(text: string): { value: Record<string, unknown> | null; error: string | null } {
  const trimmed = text.trim();
  if (!trimmed) return { value: null, error: null };
  const fenced = trimmed.replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/, "").trim();
  const start = fenced.indexOf("{");
  const end = fenced.lastIndexOf("}");
  if (start < 0 || end <= start) return { value: null, error: "не найден JSON-объект в фигурных скобках" };
  try {
    const parsed = JSON.parse(fenced.slice(start, end + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? { value: parsed as Record<string, unknown>, error: null }
      : { value: null, error: "это не JSON-объект" };
  } catch (e) {
    return { value: null, error: `JSON не разобран: ${(e as Error).message}` };
  }
}
