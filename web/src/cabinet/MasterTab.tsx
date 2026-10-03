import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import PersonaEditor from "../components/PersonaEditor";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import PersonaPicker from "./PersonaPicker";
import { api } from "../lib/api";
import {
  personaBody,
  PROVIDER_RU,
  TTS_VOICES,
  type CampaignOptions,
  type MasterPreset,
  type Persona,
  type PersonaPick,
  type Room,
} from "../lib/campaign";

interface MasterModel {
  provider: string;
  model: string;
  resolved_model: string | null;
  model_profile_id: string | null;
  model_profile_name: string | null;
}

interface CampaignPersona {
  name: string | null;
  source: "profile" | "preset" | "custom" | "legacy" | null;
  style: string | null;
}

/** ИИ-мастер кампании: модель и характер. Меняются между ходами: следующий ход мастер сделает уже по-новому. */
export default function MasterTab({
  campaignId,
  room,
  onRoom,
}: {
  campaignId: string;
  room?: Room;
  onRoom?: (r: Room) => void;
}) {
  const qc = useQueryClient();
  const model = useQuery({
    queryKey: ["master-model", campaignId],
    queryFn: () => api<MasterModel>(`/api/campaigns/${campaignId}/master-model`),
  });
  const persona = useQuery({
    queryKey: ["master-persona", campaignId],
    queryFn: () => api<CampaignPersona>(`/api/campaigns/${campaignId}/master-persona`),
  });
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const mine = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas") });
  const presets = useQuery({ queryKey: ["master-presets"], queryFn: () => api<MasterPreset[]>("/api/me/master-presets") });

    const [pick, setPick] = useState<PersonaPick>("");
  const [style, setStyle] = useState("");
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [showSavePreset, setShowSavePreset] = useState(false);
  const [savePresetName, setSavePresetName] = useState("");
  const [saveOverwriteId, setSaveOverwriteId] = useState("");
  const [characterRev, setCharacterRev] = useState(0);
  const ttsEnabled = (room?.settings?.tts_enabled ?? true) !== false;

  useEffect(() => {
      }, [model.data?.model_profile_id]);

  useEffect(() => {
    const cur = persona.data;
    if (!cur || !opts.data) return;
    if (cur.source === "preset") {
      setPick(`pre:${opts.data.presets.find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
    } else if (cur.source === "profile") {
      setPick(`my:${(mine.data ?? []).find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
    } else {
      setPick("");
    }
    setStyle(cur.style ?? "");
  }, [persona.data, opts.data, mine.data]);

  const problem = model.error ?? persona.error ?? opts.error;
  if (problem) {
    return (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось загрузить настройки ИИ-мастера: {(problem as Error).message}
      </div>
    );
  }

  if (!model.data || !persona.data || !opts.data) {
    return (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Связываемся с нейросетевым терминалом мастера…
      </div>
    );
  }

  const m = model.data;
  const p = persona.data;

  const presetOptions: SelectOption[] = (presets.data ?? []).map((x) => ({
    value: x.id,
    label: x.name,
    sublabel: x.model_profile_name ? `Модель: ${x.model_profile_name}` : "Модель по умолчанию",
    badge: "ПРЕСЕТ",
    badgeTone: "patina" as const,
  }));

  return (
    <div className="flex flex-col gap-6">
      {/* Master Presets Card */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-3">
          <div>
            <h2 className="font-heading text-xl font-bold text-ink">Пресеты мастера</h2>
            <p className="mt-0.5 text-xs text-muted">
              Сохраняйте проверенную связку модели, тона и анкеты мастера или применяйте готовый пресет к этому столу.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline-copper font-mono text-xs self-start sm:self-center"
            onClick={() => setShowSavePreset((v) => !v)}
          >
            {showSavePreset ? "✕ ЗАКРЫТЬ СОХРАНЕНИЕ" : "💾 СОХРАНИТЬ КАК ПРЕСЕТ"}
          </button>
        </div>

        {/* Save preset form */}
        {showSavePreset && (
          <div className="rounded-[10px] border border-accent/40 bg-accent/5 p-4 flex flex-col gap-3">
            <h3 className="font-heading text-sm font-bold text-ink">
              Сохранить текущую конфигурацию мастера как пресет
            </h3>
            <p className="text-xs text-muted">
              В пресет войдут: текущая модель ({m.model_profile_name || (PROVIDER_RU[m.provider] ?? m.provider) || m.model}),
              настройки тона и стиля, а также заполненная анкета характера мастера.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-end">
              <div className="flex-1 min-w-0">
                <Field label="Название пресета">
                  <input
                    className="field text-sm"
                    maxLength={64}
                    placeholder="например: Мрачный тактик D&D"
                    value={savePresetName}
                    onChange={(e) => setSavePresetName(e.target.value)}
                  />
                </Field>
              </div>
              {presets.data && presets.data.length > 0 && (
                <div className="flex-1 min-w-0">
                  <Field label="Или перезаписать существующий">
                    <CustomSelect
                      value={saveOverwriteId}
                      options={[
                        { value: "", label: "Создать новый пресет", badge: "НОВЫЙ", badgeTone: "accent" },
                        ...presets.data.map((pr) => ({
                          value: pr.id,
                          label: pr.name,
                          sublabel: pr.model_profile_name || pr.provider || undefined,
                          badge: "ПЕРЕЗАПИСЬ",
                          badgeTone: "patina" as const,
                        })),
                      ]}
                      onChange={(val) => {
                        setSaveOverwriteId(val);
                        if (val) {
                          const found = presets.data?.find((pr) => pr.id === val);
                          if (found) setSavePresetName(found.name);
                        }
                      }}
                      placeholder="Выберите пресет..."
                    />
                  </Field>
                </div>
              )}
              <ActionButton
                primary
                className="font-mono text-xs whitespace-nowrap"
                run={async () => {
                  if (!savePresetName.trim()) throw new Error("Укажите название пресета");
                  await api<MasterPreset>(`/api/campaigns/${campaignId}/save-master-preset`, {
                    method: "POST",
                    body: { name: savePresetName.trim(), preset_id: saveOverwriteId || null },
                  });
                  await qc.invalidateQueries({ queryKey: ["master-presets"] });
                  setShowSavePreset(false);
                  setSavePresetName("");
                  setSaveOverwriteId("");
                }}
                done="Пресет мастера сохранён"
              >
                СОХРАНИТЬ
              </ActionButton>
            </div>
          </div>
        )}

        {/* Apply preset form */}
        {presets.data && presets.data.length > 0 ? (
          <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3 pt-1">
            <div className="flex-1 min-w-0">
              <Field
                label="Применить сохранённый пресет к столу"
                hint="Заменит модель, тон нарратива и анкету характера мастера на настройки из пресета."
              >
                <CustomSelect
                  value={selectedPresetId}
                  options={presetOptions}
                  onChange={setSelectedPresetId}
                  placeholder="Выберите пресет мастера..."
                  ariaLabel="Пресет мастера"
                />
              </Field>
            </div>
            <ActionButton
              primary
              className="font-mono text-xs tracking-wider whitespace-nowrap"
              run={async () => {
                if (!selectedPresetId) throw new Error("Выберите пресет мастера");
                const res = await api<{
                  ok: boolean;
                  model: MasterModel;
                  persona: CampaignPersona;
                  character: unknown;
                }>(`/api/campaigns/${campaignId}/apply-master-preset/${selectedPresetId}`, {
                  method: "POST",
                });
                qc.setQueryData(["master-model", campaignId], res.model);
                qc.setQueryData(["master-persona", campaignId], res.persona);
                qc.setQueryData(["persona", `/api/campaigns/${campaignId}/master-character`, ""], res.character);
                                if (res.persona.source === "preset") {
                  setPick(`pre:${opts.data?.presets.find((p) => p.name === res.persona.name)?.id ?? ""}` as PersonaPick);
                } else if (res.persona.source === "profile") {
                  setPick(`my:${(mine.data ?? []).find((p) => p.name === res.persona.name)?.id ?? ""}` as PersonaPick);
                } else {
                  setPick("");
                }
                setStyle(res.persona.style ?? "");
                setCharacterRev((r) => r + 1);
              }}
              done="Пресет применён к столу"
            >
              ПРИМЕНИТЬ ПРЕСЕТ
            </ActionButton>
          </div>
        ) : (
          <p className="text-xs text-muted">
            У вас пока нет сохранённых пресетов мастера. Вы можете настроить параметры ниже и нажать «Сохранить как пресет», чтобы использовать их в новых кампаниях.
          </p>
        )}
      </section>

      {/* Master Voice */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-3" aria-label="Озвучка мастера">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Озвучка мастера</h2>
          <p className="text-xs text-muted">
            Голосовой синтез речи (Gemini TTS) для реплик и описаний ИИ-мастера. Выключено — мастер отвечает только
            текстом, без генерации аудиодорожек.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className={`font-mono text-xs ${ttsEnabled ? "text-patina-hi" : "text-muted"}`}>
            {ttsEnabled ? "● включено" : "○ выключено"}
          </span>
          <ActionButton
            className="btn-outline-copper"
            done={ttsEnabled ? "Озвучка мастера выключена" : "Озвучка мастера включена: реплики мастера будут озвучиваться"}
            run={async () => {
              const updated = await api<Room>(`/api/campaigns/${campaignId}`, {
                method: "PATCH",
                body: { tts_enabled: !ttsEnabled },
              });
              onRoom?.(updated);
            }}
          >
            {ttsEnabled ? "Выключить озвучку" : "Включить озвучку"}
          </ActionButton>
        </div>

        {ttsEnabled && (
          <>
            <div className="pt-2 border-t border-line/60 flex flex-col gap-2">
              <Field
                label="Источник озвучки (TTS Provider)"
                hint="Выберите сервис для синтеза речи (облачный Gemini или локальный XTTS / Silero)."
              >
                <CustomSelect
                  value={room?.settings?.tts_provider || "gemini"}
                  options={[
                    { value: "gemini", label: "Gemini TTS (Cloud)" },
                    { value: "xtts", label: "XTTS v2 (Local)" },
                    { value: "silero", label: "Silero TTS (Local)" },
                  ]}
                  onChange={async (val) => {
                    if (val === (room?.settings?.tts_provider || "gemini")) return;
                    const updated = await api<Room>(`/api/campaigns/${campaignId}`, {
                      method: "PATCH",
                      body: { tts_provider: val },
                    });
                    onRoom?.(updated);
                  }}
                  ariaLabel="Источник озвучки"
                />
              </Field>
            </div>

            <div className="pt-2 border-t border-line/60 flex flex-col gap-2">
              <Field
                label="Голос ИИ-мастера (Gemini)"
                hint="Голос, которым озвучиваются описания сцен и реплики мастера в чате."
              >
              <CustomSelect
                value={room?.settings?.tts_voice || "Fenrir"}
                options={TTS_VOICES.map((v) => ({
                  value: v.id,
                  label: v.name,
                  sublabel: `${v.gender} · ${v.description}`,
                  badge: v.id === "Fenrir" ? "ПО УМОЛЧАНИЮ" : v.gender.toUpperCase(),
                  badgeTone: v.id === "Fenrir" ? ("accent" as const) : ("patina" as const),
                }))}
                onChange={async (val) => {
                  if (val === (room?.settings?.tts_voice || "Fenrir")) return;
                  const updated = await api<Room>(`/api/campaigns/${campaignId}`, {
                    method: "PATCH",
                    body: { tts_voice: val },
                  });
                  onRoom?.(updated);
                }}
                ariaLabel="Голос мастера"
              />
            </Field>
          </div>
          </>
        )}
      </section>

      {/* Persona and Tone */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Характер и стиль повествования</h2>
          <p className="mt-0.5 text-xs text-muted">
            Сейчас:{" "}
            <span className="text-accent font-mono">
              {p.name ?? (p.source === "custom" ? "своя настройка" : p.style ? p.style : "мастер по умолчанию")}
            </span>
          </p>
        </div>

        <Field label="Базовый характер">
          <PersonaPicker value={pick} onChange={setPick} opts={opts.data} mine={mine.data ?? []} />
        </Field>

        <Field
          label="Дополнительные указания мастеру своими словами"
          hint="Например «говорит витиевато», «любит подчеркивать запахи и холод», «осторожен в бою»."
        >
          <textarea
            className="field min-h-20 text-sm"
            maxLength={2000}
            placeholder="Индивидуальные инструкции к манере ведения..."
            value={style}
            onChange={(e) => setStyle(e.target.value)}
          />
        </Field>

        <div className="pt-1">
          <ActionButton
            primary
            className="font-mono text-xs tracking-wider"
            run={async () => {
              qc.setQueryData(
                ["master-persona", campaignId],
                await api<CampaignPersona>(`/api/campaigns/${campaignId}/master-persona`, {
                  method: "PUT",
                  body: { ...personaBody(pick), style: style.trim() || null },
                }),
              );
            }}
            done="Новый тон вступит в силу со следующего ответа мастера"
          >
            ОБНОВИТЬ СТИЛЬ МАСТЕРА
          </ActionButton>
        </div>
      </section>

      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Характер мастера</h2>
          <p className="mt-0.5 text-xs text-muted">
            Поверх тона выше: свободный текст и подсказки. Мастер меняется по ходу игры — это видно в летописи.
          </p>
        </div>
        <PersonaEditor key={characterRev} base={`/api/campaigns/${campaignId}/master-character`} master />
      </section>
    </div>
  );
}
