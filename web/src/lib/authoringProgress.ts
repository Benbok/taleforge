// Что заполнено в лоре и сюжете. Пороги совпадают с серверной проверкой, поэтому «всё зелёное» здесь
// означает, что сервер тоже примет.

export interface ProgressItem {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
}

type Data = Record<string, unknown> | null | undefined;

const text = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function count(key: string, label: string, data: Data, need: number, noun: string): ProgressItem {
  const n = list(data?.[key]).length;
  return { key, label, ok: n >= need, detail: n ? `${n} ${noun}${n < need ? `, нужно от ${need}` : ""}` : `пусто, нужно от ${need}` };
}

function filled(key: string, label: string, data: Data, min = 1): ProgressItem {
  const t = text(data?.[key]);
  const ok = t.length >= min;
  return { key, label, ok, detail: !t ? "пусто" : ok ? `${t.length} символов` : `${t.length} символов, нужно от ${min}` };
}

export function loreProgress(lore: Data): ProgressItem[] {
  const factions = list(lore?.factions);
  const factionsOk = factions.length >= 2 && factions.every((f) => f && typeof f === "object" && text((f as Record<string, unknown>).goal) && text((f as Record<string, unknown>).relations));
  const factionsDetail = !factions.length ? "пусто, нужно от 2" : factions.length < 2 ? `${factions.length}, нужно от 2` : factionsOk ? `${factions.length} фракции` : "у каждой нужны цель и отношения";
  return [
    filled("overview", "Обзор мира", lore, 200),
    filled("era_and_magic", "Эпоха и магия", lore),
    count("regions", "Области", lore, 2, "обл."),
    count("history", "Хронология", lore, 4, "событ."),
    { key: "factions", label: "Фракции", ok: factionsOk, detail: factionsDetail },
    count("figures", "Ключевые фигуры", lore, 2, "фиг."),
    filled("current_situation", "Что происходит сейчас", lore),
    count("mysteries", "Тайны мира", lore, 2, "тайн."),
    filled("tone", "Тон", lore),
  ];
}

export function plotProgress(plan: Data): ProgressItem[] {
  return [
    filled("title", "Название", plan),
    filled("tagline", "Слоган", plan),
    filled("public_intro", "Завязка для игроков", plan),
    filled("conflict", "Конфликт", plan),
    filled("stakes", "Ставки", plan),
    count("antagonists", "Антагонисты", plan, 1, "шт."),
    count("locations", "Места", plan, 2, "мест."),
    count("npcs", "NPC", plan, 2, "шт."),
    count("acts", "Акты", plan, 1, "шт."),
    count("reveals", "Тайны и улики", plan, 1, "шт."),
    count("endings", "Финалы", plan, 1, "шт."),
  ];
}

export function done(items: ProgressItem[]): number {
  return items.filter((i) => i.ok).length;
}
