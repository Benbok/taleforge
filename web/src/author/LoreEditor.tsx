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
    <section aria-label="Лор мира" className="flex flex-col gap-6">
      {legacy && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm text-warn" role="status">
          <p className="font-medium">Это лор старого короткого формата.</p>
          <p className="mt-1 text-xs">Нажмите «Новый вариант» у этапа «Лор», чтобы получить подробный многоуровневый лор.</p>
        </div>
      )}

      {/* Основные тексты */}
      <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
        <h3 className="font-heading text-sm font-semibold uppercase tracking-wider text-muted">Атмосфера и основы мира</h3>
        {(legacy ? [["world", "Описание мира"] as [string, string], ...TEXT] : TEXT).map(([key, label]) => (
          <label key={key} id={`lore-${key}`} className="flex scroll-mt-24 flex-col gap-1.5 text-sm">
            <span className="font-medium text-ink">{label}</span>
            <textarea
              aria-label={label}
              className={`rounded-xl border border-line bg-raised p-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none ${
                key === "overview" ? "min-h-36 leading-relaxed" : "min-h-24"
              }`}
              value={String(value(key) ?? "")}
              onChange={(e) => set(key, e.target.value)}
            />
          </label>
        ))}
      </div>

      {/* Структурированные записи */}
      <div className="flex flex-col gap-5 rounded-xl border border-line bg-surface p-4">
        <h3 className="font-heading text-sm font-semibold uppercase tracking-wider text-muted">Фракции, фигуры и география</h3>
        {RECORDS.map(([key, label, fields]) => {
          if (key === "factions" && legacyFactions) {
            return (
              <label key={key} id={`lore-${key}`} className="flex scroll-mt-24 flex-col gap-1.5 text-sm">
                <span className="font-medium text-ink">{label} (по строке)</span>
                <textarea
                  className="min-h-24 rounded-xl border border-line bg-raised p-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                  value={(factions as string[]).join("\n")}
                  onChange={(e) => set(key, e.target.value.split("\n"))}
                />
              </label>
            );
          }
          const items = (value(key) as Records | undefined) ?? [];
          if (typeof value(key) === "string") {
            return (
              <label key={key} id={`lore-${key}`} className="flex scroll-mt-24 flex-col gap-1.5 text-sm">
                <span className="font-medium text-ink">{label}</span>
                <textarea
                  className="min-h-24 rounded-xl border border-line bg-raised p-3 text-sm text-ink"
                  value={String(value(key))}
                  readOnly
                />
              </label>
            );
          }
          return (
            <fieldset key={key} id={`lore-${key}`} className="flex scroll-mt-24 flex-col gap-3">
              <div className="flex items-center justify-between border-b border-line-soft pb-2">
                <legend className="font-medium text-ink">{label}</legend>
                <span className="text-xs text-muted">{items.length} зап.</span>
              </div>
              <div className="flex flex-col gap-2.5">
                {items.map((item, i) => (
                  <div
                    key={i}
                    className="flex flex-col gap-2 rounded-xl border border-line bg-raised/70 p-3"
                    aria-label={`${label} ${i + 1}`}
                  >
                    <div className="grid gap-2 sm:grid-cols-2">
                      {fields.map(([field, fieldLabel]) => (
                        <label key={field} className="flex flex-col gap-1 text-xs text-muted">
                          <span>{fieldLabel}</span>
                          <input
                            className="min-h-10 rounded-lg border border-line bg-surface px-2.5 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                            aria-label={`${fieldLabel} ${i + 1}`}
                            placeholder={fieldLabel}
                            value={item[field] ?? ""}
                            onChange={(e) =>
                              set(
                                key,
                                items.map((x, j) => (j === i ? { ...x, [field]: e.target.value } : x))
                              )
                            }
                          />
                        </label>
                      ))}
                    </div>
                    <div className="flex justify-end pt-1">
                      <button
                        type="button"
                        className="btn min-h-8 px-2.5 text-xs text-bad hover:border-bad/40"
                        onClick={() => set(key, items.filter((_, j) => j !== i))}
                      >
                        Убрать {label.toLowerCase().slice(0, -1)}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="btn min-h-10 self-start px-3 text-xs"
                onClick={() => set(key, [...items, {}])}
              >
                + Добавить в «{label}»
              </button>
            </fieldset>
          );
        })}
      </div>

      {/* Списки тайн и табу */}
      <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
        <h3 className="font-heading text-sm font-semibold uppercase tracking-wider text-muted">Тайны и границы</h3>
        {LISTS.map(([key, label]) => (
          <label key={key} id={`lore-${key}`} className="flex scroll-mt-24 flex-col gap-1.5 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium text-ink">{label}</span>
              <span className="text-xs text-muted">по строке на пункт</span>
            </div>
            <textarea
              className="min-h-24 rounded-xl border border-line bg-raised p-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
              value={((value(key) as string[] | undefined) ?? []).join("\n")}
              onChange={(e) => set(key, e.target.value.split("\n"))}
            />
          </label>
        ))}
      </div>

      {/* Панель сохранения */}
      <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface/95 p-3 shadow-lg backdrop-blur-sm">
        <div className="text-xs text-muted">
          {changed ? (
            <span className="text-accent font-medium">Есть несохраненные изменения</span>
          ) : (
            <span>Все изменения в лоре сохранены</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {changed && (
            <button
              className="btn min-h-10 px-3 text-sm"
              type="button"
              onClick={() => setDraft({})}
            >
              Отменить
            </button>
          )}
          <button
            className="btn btn-primary min-h-10 px-4 text-sm font-medium"
            type="button"
            disabled={busy || !changed}
            onClick={() => {
              const fields: Record<string, unknown> = {};
              for (const [k, v] of Object.entries(draft)) {
                fields[k] =
                  Array.isArray(v) && v.every((x) => typeof x === "string")
                    ? (v as string[]).map((x) => x.trim()).filter(Boolean)
                    : v;
              }
              onSave(fields);
              setDraft({});
            }}
          >
            Сохранить лор
          </button>
        </div>
      </div>
    </section>
  );
}
