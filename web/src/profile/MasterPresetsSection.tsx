import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import PersonaPicker from "../cabinet/PersonaPicker";
import { api } from "../lib/api";
import {
  personaBody,
  PROVIDER_RU,
  type CampaignOptions,
  type MasterPreset,
  type ModelProfile,
  type Persona,
  type PersonaPick,
} from "../lib/campaign";

const MASTER_FIELDS: [string, string, string][] = [
  ["tricks", "Коронные приёмы и фразы", "Особые повествовательные привычки, жесты, звуки костей или паузы"],
  ["samples", "Примеры речи и реплик", "Живые цитаты или реплики мастера в начале сцен или при проверках"],
  ["never", "Чего мастер никогда не делает", "Табу мастера: не подсказывает напрямую, не ломает четвёртую стену и т.д."],
  ["party", "Отношение к партии", "Как мастер смотрит на героев: наставник, строгий судья или беспристрастный летописец"],
];

interface PresetFormState {
  id: string | null;
  name: string;
  model_profile_id: string;
  persona_pick: PersonaPick;
  style: string;
  character_text: string;
  character_fields: Record<string, string>;
  character_core: string[];
}

interface Scene {
  scene: string;
  situation: string;
  reply: string;
}

/** Библиотека пресетов мастера (Нейросетевая модель мастера). */
export default function MasterPresetsSection() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["master-presets"], queryFn: () => api<MasterPreset[]>("/api/me/master-presets") });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<ModelProfile[]>("/api/admin/models") });
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas") });

  const [form, setForm] = useState<PresetFormState | null>(null);
  const [formScenes, setFormScenes] = useState<Scene[] | null>(null);
  const [cardTestId, setCardTestId] = useState<string | null>(null);
  const [cardScenes, setCardScenes] = useState<Scene[] | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["master-presets"] });

  const defModel = (models.data ?? []).find((m) => m.is_default);
  const modelOptions: SelectOption[] = [
    {
      value: "",
      label: defModel ? `По умолчанию (${defModel.name})` : "По умолчанию (рекомендуемая модель)",
      sublabel: defModel?.resolved_model || "Системная рекомендуемая нейросеть",
      badge: "СИСТЕМНАЯ",
      badgeTone: "accent",
    },
    ...(models.data ?? []).map((m) => ({
      value: m.id,
      label: m.name,
      sublabel: `${PROVIDER_RU[m.provider] ?? m.provider} · ${m.resolved_model || m.model}`,
      badge: PROVIDER_RU[m.provider]?.toUpperCase(),
      badgeTone: m.is_default ? ("accent" as const) : ("patina" as const),
    })),
  ];

  return (
    <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-5" aria-label="Пресеты мастера">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">Библиотека пресетов мастера</h2>
          <p className="mt-0.5 text-xs text-muted max-w-2xl">
            Сохранённые конфигурации ИИ-мастера: модель, нарративный тон и анкета характера с коронными приёмами и правилами.
            Позволяет быстро запускать новые кампании с уже проверенным и протестированным стилем ведения.
          </p>
        </div>

        {!form && (
          <button
            type="button"
            className="btn btn-outline-copper font-mono text-xs self-start sm:self-center"
            onClick={() => {
              setForm({
                id: null,
                name: "",
                model_profile_id: "",
                persona_pick: "pre:storyteller",
                style: "",
                character_text: "",
                character_fields: {},
                character_core: ["samples", "never"],
              });
              setFormScenes(null);
              setCardTestId(null);
              setCardScenes(null);
            }}
          >
            + СОЗДАТЬ ПРЕСЕТ
          </button>
        )}
      </div>

      {list.isError && (
        <div className="card border-bad/40 bg-bad/5 p-4 text-xs text-bad">
          Не удалось загрузить список пресетов: {(list.error as Error).message}
        </div>
      )}

      {list.isSuccess && list.data.length === 0 && (
        <p className="text-xs sm:text-sm text-muted">
          Сохранённых пресетов пока нет. Вы можете создать пресет мастера здесь или сохранить его прямо из кабинета активной кампании.
        </p>
      )}

      {/* Preset Cards Grid */}
      <div className="grid gap-3 sm:grid-cols-2">
        {(list.data ?? []).map((pr) => {
          const isTestingThis = cardTestId === pr.id;
          return (
            <div
              key={pr.id}
              className="card group relative flex flex-col justify-between gap-3 p-4 border border-line bg-raised/40 hover:border-accent/60 transition"
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
                  <span className="font-heading text-base font-bold text-ink group-hover:text-accent transition">
                    {pr.name}
                  </span>
                  <span className="font-mono text-[10px] text-accent px-1.5 py-0.5 rounded border border-accent/30 bg-accent/10">
                    ПРЕСЕТ МАСТЕРА
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-muted">
                  <span className="text-ink-2">Модель:</span>
                  <span className="text-patina-hi">
                    {pr.model_profile_name || (pr.provider ? PROVIDER_RU[pr.provider] ?? pr.provider : "По умолчанию")}
                  </span>
                </div>

                {pr.style_preview && (
                  <p className="text-xs font-serif italic text-muted line-clamp-2">
                    «{pr.style_preview}»
                  </p>
                )}

                {pr.character?.text && (
                  <div className="rounded border border-line/40 bg-surface/50 p-2 text-xs text-ink-2 line-clamp-2">
                    <span className="font-mono text-[10px] text-muted block mb-0.5 uppercase">Характер:</span>
                    {pr.character.text}
                  </div>
                )}

                {/* Show card test scenes if loaded */}
                {isTestingThis && cardScenes && (
                  <div className="mt-2 flex flex-col gap-2 border-t border-line/40 pt-2">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] text-accent uppercase font-semibold">
                        Пробные сцены мастера:
                      </span>
                      <button
                        type="button"
                        className="text-xs font-mono text-muted hover:text-ink"
                        onClick={() => {
                          setCardTestId(null);
                          setCardScenes(null);
                        }}
                      >
                        ✕ Скрыть
                      </button>
                    </div>
                    {cardScenes.map((s, idx) => (
                      <div key={idx} className="rounded border border-line bg-raised/80 p-2 text-xs">
                        <div className="font-mono text-[10px] text-accent font-semibold">{s.scene}</div>
                        <div className="text-muted text-[11px] mt-0.5">{s.situation}</div>
                        <div className="italic text-ink text-[11px] mt-1">«{s.reply}»</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-line/40">
                <ActionButton
                  className="px-2.5 py-1 text-xs font-mono"
                  run={async () => {
                    setCardTestId(pr.id);
                    const res = await api<{ scenes: Scene[] }>("/api/me/master-presets/test", {
                      method: "POST",
                      body: {
                        model_profile_id: pr.model_profile_id,
                        style: pr.style,
                        character: pr.character,
                      },
                    });
                    setCardScenes(res.scenes);
                  }}
                  done="Сцены готовы"
                >
                  Проверить
                </ActionButton>

                <button
                  type="button"
                  className="btn px-2.5 py-1 text-xs font-mono"
                  onClick={() => {
                    setForm({
                      id: pr.id,
                      name: pr.name,
                      model_profile_id: pr.model_profile_id ?? "",
                      persona_pick: (pr.persona_preset
                        ? `pre:${pr.persona_preset}`
                        : pr.persona_id
                          ? `my:${pr.persona_id}`
                          : "") as PersonaPick,
                      style: pr.style ?? "",
                      character_text: pr.character?.text ?? "",
                      character_fields: pr.character?.fields ?? {},
                      character_core: pr.character?.core ?? ["samples", "never"],
                    });
                    setFormScenes(null);
                    setCardTestId(null);
                    setCardScenes(null);
                  }}
                >
                  Изменить
                </button>

                <ActionButton
                  danger
                  className="px-2.5 py-1 text-xs font-mono"
                  confirm="Удалить пресет мастера? Кампании, где он уже применён, продолжат работу без изменений."
                  run={async () => {
                    await api(`/api/me/master-presets/${pr.id}`, { method: "DELETE" });
                    await refresh();
                  }}
                  done="Пресет удалён"
                >
                  Удалить
                </ActionButton>
              </div>
            </div>
          );
        })}
      </div>

      {/* Create / Edit Form */}
      {form && (
        <div className="rounded-[12px] border-2 border-accent/50 bg-raised/30 p-5 flex flex-col gap-4 mt-2">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="font-heading text-lg font-bold text-ink">
              {form.id ? "Редактировать пресет мастера" : "Новый пресет мастера"}
            </h3>
            <button
              type="button"
              className="text-xs font-mono text-muted hover:text-ink"
              onClick={() => {
                setForm(null);
                setFormScenes(null);
              }}
            >
              ✕ ЗАКРЫТЬ
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Название пресета">
              <input
                className="field text-sm"
                maxLength={64}
                placeholder="например: Мрачный тактик подземелий"
                value={form.name}
                autoFocus
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>

            <Field label="Нейросетевая модель мастера">
              <CustomSelect
                value={form.model_profile_id}
                options={modelOptions}
                onChange={(val) => setForm({ ...form, model_profile_id: val })}
                ariaLabel="Модель мастера"
              />
            </Field>
          </div>

          {opts.data && (
            <Field
              label="Базовый нарративный характер и тон"
              hint="Определяет слайдеры мрачности, юмора и многословия."
            >
              <PersonaPicker
                value={form.persona_pick}
                onChange={(persona_pick) => setForm({ ...form, persona_pick })}
                opts={opts.data}
                mine={personas.data ?? []}
              />
            </Field>
          )}

          <Field
            label="Дополнительные указания мастеру своими словами"
            hint="Например «любит описывать звуки и запахи», «держит напряжение в боях», «использует метафоры моря»."
          >
            <textarea
              className="field min-h-20 text-sm"
              maxLength={2000}
              placeholder="Индивидуальные инструкции к манере ведения..."
              value={form.style}
              onChange={(e) => setForm({ ...form, style: e.target.value })}
            />
          </Field>

          {/* Character sheet */}
          <div className="flex flex-col gap-3 border-t border-line/60 pt-4">
            <div>
              <h4 className="font-heading text-base font-bold text-ink">Анкета характера мастера</h4>
              <p className="mt-0.5 text-xs text-muted">
                Свободный текст и коронные приёмы. Попадают в системный промпт ИИ-мастера для стабильности его образа.
              </p>
            </div>

            <Field label="Какой он мастер — своими словами" hint="Краткое описание манеры вести приключение.">
              <textarea
                className="field min-h-20 text-sm"
                maxLength={4000}
                placeholder="например: Вдумчивый сказитель, безжалостен к ошибкам, но поощряет смекалку и командную работу..."
                value={form.character_text}
                onChange={(e) => setForm({ ...form, character_text: e.target.value })}
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              {MASTER_FIELDS.map(([k, label, hint]) => (
                <Field key={k} label={label} hint={hint}>
                  <textarea
                    className="field min-h-16 text-sm"
                    maxLength={1000}
                    value={form.character_fields[k] ?? ""}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        character_fields: { ...form.character_fields, [k]: e.target.value },
                      })
                    }
                  />
                </Field>
              ))}
            </div>
          </div>

          {/* Trial scenes in form */}
          {formScenes && (
            <div className="rounded-[8px] border border-line bg-raised/80 p-3 flex flex-col gap-2.5">
              <div className="flex items-center justify-between border-b border-line/40 pb-1.5">
                <span className="font-mono text-xs text-accent font-semibold uppercase">
                  Пробные ответы мастера по текущей анкете:
                </span>
                <button
                  type="button"
                  className="text-xs font-mono text-muted hover:text-ink"
                  onClick={() => setFormScenes(null)}
                >
                  ✕ Скрыть
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                {formScenes.map((s, idx) => (
                  <div key={idx} className="rounded border border-line bg-surface p-2.5 text-xs flex flex-col gap-1">
                    <span className="font-mono text-[10px] text-accent font-bold uppercase">{s.scene}</span>
                    <span className="text-muted text-[11px]">{s.situation}</span>
                    <span className="italic text-ink text-[11px] mt-1">«{s.reply}»</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <ActionButton
              primary
              className="font-mono text-xs tracking-wider"
              run={async () => {
                if (!form.name.trim()) throw new Error("Укажите название пресета");
                const pick = personaBody(form.persona_pick);
                const body = {
                  name: form.name.trim(),
                  model_profile_id: form.model_profile_id || null,
                  persona_preset: pick.preset || null,
                  persona_id: pick.persona_id || null,
                  style: form.style.trim() || null,
                  character: {
                    text: form.character_text.trim(),
                    fields: form.character_fields,
                    core: form.character_core,
                  },
                };
                if (form.id) {
                  await api(`/api/me/master-presets/${form.id}`, { method: "PATCH", body });
                } else {
                  await api("/api/me/master-presets", { method: "POST", body });
                }
                setForm(null);
                setFormScenes(null);
                await refresh();
              }}
              done="Пресет мастера сохранён"
            >
              СОХРАНИТЬ ПРЕСЕТ
            </ActionButton>

            <ActionButton
              className="font-mono text-xs"
              run={async () => {
                const res = await api<{ scenes: Scene[] }>("/api/me/master-presets/test", {
                  method: "POST",
                  body: {
                    model_profile_id: form.model_profile_id || null,
                    style: form.style.trim() || null,
                    character: {
                      text: form.character_text.trim(),
                      fields: form.character_fields,
                      core: form.character_core,
                    },
                  },
                });
                setFormScenes(res.scenes);
              }}
              done="Сцены сгенерированы"
            >
              Проверить пробные сцены
            </ActionButton>

            <button
              type="button"
              className="btn text-xs font-mono text-muted hover:text-ink ml-auto"
              onClick={() => {
                setForm(null);
                setFormScenes(null);
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
