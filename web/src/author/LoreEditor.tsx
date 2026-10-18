import { useState } from "react";

type Records = Record<string, string>[];
export type Lore = Record<string, string | string[] | Records | undefined>;

const TEXT: [string, string][] = [
  ["overview", "Обзор мира"],
  ["era_and_magic", "Эпоха и магия"],
  ["current_situation", "Что происходит сейчас"],
  ["tone", "Тон"],
];
const RECORDS: [string, string, [string, string][]][] = [
  ["regions", "Области", [["name", "Название"], ["description", "Описание"]]],
  ["history", "Хронология", [["when", "Когда"], ["event", "Событие"]]],
  ["factions", "Фракции", [["name", "Название"], ["goal", "Цель"], ["resources", "Ресурсы"], ["relations", "Отношения"], ["secret", "Тайна"]]],
  ["figures", "Ключевые фигуры", [["name", "Имя"], ["role", "Кто это"], ["motive", "Мотив"]]],
];
const LISTS: [string, string][] = [
  ["mysteries", "Тайны мира"],
  ["taboos", "Чего избегать"],
];

interface Props {
  lore: Lore;
  busy: boolean;
  onSave(fields: Record<string, unknown>): void;
}

/** Все разделы лора: текст правится целиком, записи — по полям, списки — по строке на пункт. */
export default function LoreEditor({ lore, busy, onSave }: Props) {
  const [draft, setDraft] = useState<Lore>({});
  const value = (key: string) => (key in draft ? draft[key] : lore[key]);
  const set = (key: string, v: Lore[string]) => setDraft({ ...draft, [key]: v });
  const changed = Object.keys(draft).length > 0;
  const legacy = typeof lore.world === "string" && !lore.overview;
  const factions = value("factions");
  const legacyFactions = Array.isArray(factions) && factions.some((f) => typeof f === "string");

  return (
    <section aria-label="Лор мира" className="flex flex-col gap-4">
      <h2 className="font-heading text-lg text-ink">Лор мира</h2>
      {legacy && <p className="text-sm text-warn" role="status">Это лор старого короткого формата. Нажмите «Новый вариант» у этапа «Лор», чтобы получить подробный.</p>}
      {(legacy ? [["world", "Описание мира"] as [string, string], ...TEXT] : TEXT).map(([key, label]) => (
        <label key={key} className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{label}</span>
          <textarea
            className={`rounded-lg border border-line bg-raised p-2 ${key === "overview" ? "min-h-40" : "min-h-20"}`}
            value={String(value(key) ?? "")}
            onChange={(e) => set(key, e.target.value)}
          />
        </label>
      ))}
      {RECORDS.map(([key, label, fields]) => {
        if (key === "factions" && legacyFactions) {
          return (
            <label key={key} className="flex flex-col gap-1 text-sm">
              <span className="text-muted">{label} (по строке)</span>
              <textarea className="min-h-20 rounded-lg border border-line bg-raised p-2" value={(factions as string[]).join("\n")} onChange={(e) => set(key, e.target.value.split("\n"))} />
            </label>
          );
        }
        const items = (value(key) as Records | undefined) ?? [];
        if (typeof value(key) === "string") {
          return (
            <label key={key} className="flex flex-col gap-1 text-sm">
              <span className="text-muted">{label}</span>
              <textarea className="min-h-20 rounded-lg border border-line bg-raised p-2" value={String(value(key))} readOnly />
            </label>
          );
        }
        return (
          <fieldset key={key} className="flex flex-col gap-2">
            <legend className="text-sm text-muted">{label}</legend>
            {items.map((item, i) => (
              <div key={i} className="grid gap-2 rounded-lg border border-line p-2 sm:grid-cols-2" aria-label={`${label} ${i + 1}`}>
                {fields.map(([field, fieldLabel]) => (
                  <input
                    key={field}
                    className="min-h-11 rounded-lg border border-line bg-raised px-2 text-sm"
                    aria-label={`${fieldLabel} ${i + 1}`}
                    placeholder={fieldLabel}
                    value={item[field] ?? ""}
                    onChange={(e) => set(key, items.map((x, j) => (j === i ? { ...x, [field]: e.target.value } : x)))}
                  />
                ))}
                <button type="button" className="btn min-h-11 px-3 text-xs" onClick={() => set(key, items.filter((_, j) => j !== i))}>Убрать</button>
              </div>
            ))}
            <button type="button" className="btn min-h-11 self-start px-3 text-xs" onClick={() => set(key, [...items, {}])}>Добавить</button>
          </fieldset>
        );
      })}
      {LISTS.map(([key, label]) => (
        <label key={key} className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{label} (по строке на пункт)</span>
          <textarea
            className="min-h-20 rounded-lg border border-line bg-raised p-2"
            value={((value(key) as string[] | undefined) ?? []).join("\n")}
            onChange={(e) => set(key, e.target.value.split("\n"))}
          />
        </label>
      ))}
      <div className="flex gap-2">
        <button
          className="btn btn-primary min-h-11 px-3 text-sm"
          type="button"
          disabled={busy || !changed}
          onClick={() => {
            const fields: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(draft)) {
              fields[k] = Array.isArray(v) && v.every((x) => typeof x === "string") ? (v as string[]).map((x) => x.trim()).filter(Boolean) : v;
            }
            onSave(fields);
            setDraft({});
          }}
        >
          Сохранить лор
        </button>
        {changed && <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => setDraft({})}>Отменить</button>}
      </div>
    </section>
  );
}
