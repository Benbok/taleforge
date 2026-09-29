import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import type { CampaignOptions, Persona, PersonaSettings } from "../lib/campaign";

const FIELDS: [string, string][] = [
  ["seriousness", "Серьёзность"],
  ["humor", "Юмор"],
  ["darkness", "Мрачность"],
  ["verbosity", "Описания"],
  ["pace", "Темп"],
  ["manner", "Манера"],
  ["harshness", "Подача последствий"],
];

/** Персоны мастера: характер подачи ИИ-мастера. Кампания получает копию, поэтому правка здесь идущие игры не трогает. */
export default function PersonasSection() {
  const qc = useQueryClient();
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const list = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas") });
  const [form, setForm] = useState<{ id: string | null; name: string; settings: PersonaSettings } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["personas"] });
  const o = opts.data?.persona;
  const setting = (k: string, v: string | number) => setForm((f) => (f ? { ...f, settings: { ...f.settings, [k]: v } } : f));

  return (
    <section className="card flex flex-col gap-4 p-4" aria-label="Персоны мастера">
      <div>
        <h2 className="text-base font-semibold">Персоны мастера</h2>
        <p className="text-sm text-muted">Тон, юмор и манера ИИ-мастера. Механику и сложность персона не меняет. Кампания получает копию, поэтому правка здесь идущие кампании не трогает.</p>
      </div>
      {list.isError && <p className="text-bad">Не удалось загрузить персоны: {(list.error as Error).message}</p>}
      {list.isSuccess && list.data.length === 0 && <p className="text-sm text-muted">Своих персон пока нет. Можно выбирать встроенные или создать свою на их основе.</p>}
      <ul className="flex flex-col divide-y divide-line">
        {(list.data ?? []).map((p) => (
          <li key={p.id} className="flex flex-wrap items-start gap-2 py-2">
            <span className="min-w-0 flex-1">
              <span className="font-semibold">{p.name}</span>
              <span className="block whitespace-pre-line text-xs text-muted">{p.style}</span>
            </span>
            <span className="flex gap-1.5">
              <button className="btn px-2 py-0.5 text-xs" onClick={() => setForm({ id: p.id, name: p.name, settings: p.settings })}>
                Изменить
              </button>
              <ActionButton
                danger
                className="px-2 py-0.5 text-xs"
                confirm="Удалить персону? Кампании, где она выбрана, сохранят свою копию."
                run={async () => {
                  await api(`/api/me/master-personas/${p.id}`, { method: "DELETE" });
                  await refresh();
                }}
                done="Персона удалена"
              >
                Удалить
              </ActionButton>
            </span>
          </li>
        ))}
      </ul>
      {!form ? (
        <div>
          <button className="btn btn-primary" disabled={!o} onClick={() => o && setForm({ id: null, name: "", settings: { ...o.default } })}>
            Добавить персону
          </button>
        </div>
      ) : (
        o && (
          <div className="flex flex-col gap-3 rounded-md border border-line p-3">
            <h3 className="font-semibold">{form.id ? "Изменить персону" : "Новая персона"}</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Название">
                <input className="field" maxLength={64} placeholder="например «Мрачный летописец»" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label="Взять за основу">
                <select
                  className="field"
                  value=""
                  onChange={(e) => {
                    const pre = opts.data!.presets.find((p) => p.id === e.target.value);
                    if (pre) setForm({ ...form, settings: { ...pre.settings } });
                  }}
                >
                  <option value="">—</option>
                  {opts.data!.presets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
              {FIELDS.map(([k, label]) => (
                <Field key={k} label={label}>
                  <select
                    className="field"
                    value={String(form.settings[k] ?? "")}
                    onChange={(e) => setting(k, /^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value)}
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
            <Field label="Своими словами" hint="Например «говорит медленно, любит старые поговорки».">
              <textarea className="field min-h-14" maxLength={500} value={String(form.settings.notes ?? "")} onChange={(e) => setting("notes", e.target.value)} />
            </Field>
            <p className="text-sm text-muted">
              Так мастер поймёт персону: {o.seriousness?.[form.settings.seriousness]}, {o.humor?.[form.settings.humor]}, {o.darkness?.[form.settings.darkness]}; описания —{" "}
              {o.verbosity?.[form.settings.verbosity]}; манера — {o.manner?.[form.settings.manner]}.
            </p>
            <div className="flex flex-wrap gap-2">
              <ActionButton
                primary
                run={async () => {
                  if (!form.name.trim()) throw new Error("Назовите персону");
                  const body = { name: form.name.trim(), settings: form.settings };
                  await api(form.id ? `/api/me/master-personas/${form.id}` : "/api/me/master-personas", { method: form.id ? "PATCH" : "POST", body });
                  setForm(null);
                  await refresh();
                }}
                done="Персона сохранена"
              >
                Сохранить
              </ActionButton>
              <button className="btn" onClick={() => setForm(null)}>
                Отмена
              </button>
            </div>
          </div>
        )
      )}
    </section>
  );
}
