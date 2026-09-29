import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import type { CampaignOptions, Persona, PersonaSettings } from "../lib/campaign";

const FIELDS: [string, string][] = [
  ["seriousness", "Серьёзность"],
  ["humor", "Юмор"],
  ["darkness", "Мрачность"],
  ["verbosity", "Объём описаний"],
  ["pace", "Темп событий"],
  ["manner", "Манера речи"],
  ["harshness", "Подача последствий"],
];

/** Персоны мастера: характер подачи ИИ-мастера. */
export default function PersonasSection() {
  const qc = useQueryClient();
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const list = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas") });
  const [form, setForm] = useState<{ id: string | null; name: string; settings: PersonaSettings } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["personas"] });
  const o = opts.data?.persona;
  const setting = (k: string, v: string | number) =>
    setForm((f) => (f ? { ...f, settings: { ...f.settings, [k]: v } } : f));

  const presetOptions: SelectOption[] = [
    {
      value: "",
      label: "Без пресета (по умолчанию)",
      sublabel: "Базовые сбалансированные параметры",
      badge: "КАНОН",
      badgeTone: "muted",
    },
    ...(opts.data?.presets ?? []).map((p) => ({
      value: p.id,
      label: p.name,
      sublabel: p.style ? p.style.slice(0, 60) + "…" : undefined,
      badge: "ПРЕСЕТ",
      badgeTone: "patina" as const,
    })),
  ];

  return (
    <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-5" aria-label="Персоны мастера">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">Библиотека характеров (Персоны ИИ-мастера)</h2>
          <p className="mt-0.5 text-xs text-muted max-w-2xl">
            Индивидуальные стили подачи: тон, юмор и жестокость мира. Игровые правила остаются неизменными.
            Кампания получает копию персоны при создании.
          </p>
        </div>

        {!form && (
          <button
            type="button"
            className="btn btn-outline-copper font-mono text-xs self-start sm:self-center"
            disabled={!o}
            onClick={() => o && setForm({ id: null, name: "", settings: { ...o.default } })}
          >
            + СОЗДАТЬ ПЕРСОНУ
          </button>
        )}
      </div>

      {list.isError && (
        <div className="card border-bad/40 bg-bad/5 p-4 text-xs text-bad">
          Не удалось загрузить список персон: {(list.error as Error).message}
        </div>
      )}

      {list.isSuccess && list.data.length === 0 && (
        <p className="text-xs sm:text-sm text-muted">
          Своих персон пока нет. Вы можете использовать предустановленные архетипы или создать свой собственный.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {(list.data ?? []).map((p) => (
          <div
            key={p.id}
            className="card group relative flex flex-col justify-between gap-3 p-4 border border-line bg-raised/40 hover:border-accent/60 transition"
          >
            <div>
              <div className="flex items-center justify-between gap-2 border-b border-line pb-2 mb-2">
                <span className="font-heading text-base font-bold text-ink group-hover:text-accent transition">
                  {p.name}
                </span>
                <span className="font-mono text-[10px] text-accent">МОЯ ПЕРСОНА</span>
              </div>
              <p className="whitespace-pre-line text-xs font-serif italic text-muted leading-relaxed">
                «{p.style}»
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-line/40">
              <button
                type="button"
                className="btn px-2.5 py-1 text-xs font-mono"
                onClick={() => setForm({ id: p.id, name: p.name, settings: p.settings })}
              >
                Изменить
              </button>
              <ActionButton
                danger
                className="px-2.5 py-1 text-xs font-mono"
                confirm="Удалить персону? Кампании, где она уже выбрана, сохранят свою копию."
                run={async () => {
                  await api(`/api/me/master-personas/${p.id}`, { method: "DELETE" });
                  await refresh();
                }}
                done="Персона удалена"
              >
                Удалить
              </ActionButton>
            </div>
          </div>
        ))}
      </div>

      {form && o && (
        <div className="rounded-[12px] border-2 border-accent/50 bg-raised/30 p-5 flex flex-col gap-4 mt-2">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="font-heading text-lg font-bold text-ink">
              {form.id ? "Редактировать персону" : "Новая персона мастера"}
            </h3>
            <button
              type="button"
              className="text-xs font-mono text-muted hover:text-ink"
              onClick={() => setForm(null)}
            >
              ✕ ЗАКРЫТЬ
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Название персоны">
              <input
                className="field text-sm"
                maxLength={64}
                placeholder="например: Мрачный Летописец"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>

            <Field label="Взять за основу готовый пресет">
              <CustomSelect
                value=""
                options={presetOptions}
                onChange={(val) => {
                  const pre = opts.data!.presets.find((p) => p.id === val);
                  if (pre) setForm({ ...form, settings: { ...pre.settings } });
                }}
                placeholder="Выберите шаблон..."
                ariaLabel="Шаблон основы"
              />
            </Field>

            {FIELDS.map(([k, label]) => (
              <Field key={k} label={label}>
                <select
                  className="field text-sm"
                  value={String(form.settings[k] ?? "")}
                  onChange={(e) =>
                    setting(k, /^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value)
                  }
                >
                  {Object.entries(o[k] ?? {}).map(([v, text]) => (
                    <option key={v} value={v}>
                      {text}
                    </option>
                  ))}
                </select>
              </Field>
            ))}
          </div>

          <Field label="Дополнительные черты своими словами" hint="Особые поговорки, акценты или привычки мастера.">
            <textarea
              className="field min-h-16 text-sm"
              maxLength={500}
              placeholder="например: часто упоминает скрип мачт и запах пороха..."
              value={String(form.settings.notes ?? "")}
              onChange={(e) => setting("notes", e.target.value)}
            />
          </Field>

          <div className="rounded-[8px] border border-line bg-raised/80 p-3 text-xs font-mono text-muted leading-relaxed">
            <span className="text-accent font-semibold block mb-0.5">Нарративный профиль:</span>
            {o.seriousness?.[form.settings.seriousness]}, {o.humor?.[form.settings.humor]},{" "}
            {o.darkness?.[form.settings.darkness]}; описания — {o.verbosity?.[form.settings.verbosity]}; манера —{" "}
            {o.manner?.[form.settings.manner]}.
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <ActionButton
              primary
              className="font-mono text-xs"
              run={async () => {
                if (!form.name.trim()) throw new Error("Укажите название персоны");
                const body = { name: form.name.trim(), settings: form.settings };
                await api(form.id ? `/api/me/master-personas/${form.id}` : "/api/me/master-personas", {
                  method: form.id ? "PATCH" : "POST",
                  body,
                });
                setForm(null);
                await refresh();
              }}
              done="Персона мастера сохранена"
            >
              СОХРАНИТЬ ПЕРСОНУ
            </ActionButton>

            <button
              type="button"
              className="btn text-xs font-mono text-muted hover:text-ink"
              onClick={() => setForm(null)}
            >
              Отмена
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
