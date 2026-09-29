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
  type CampaignOptions,
  type ModelProfile,
  type Persona,
  type PersonaPick,
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
export default function MasterTab({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient();
  const model = useQuery({
    queryKey: ["master-model", campaignId],
    queryFn: () => api<MasterModel>(`/api/campaigns/${campaignId}/master-model`),
  });
  const persona = useQuery({
    queryKey: ["master-persona", campaignId],
    queryFn: () => api<CampaignPersona>(`/api/campaigns/${campaignId}/master-persona`),
  });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<ModelProfile[]>("/api/admin/models") });
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const mine = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas") });

  const [pickedModel, setPickedModel] = useState("");
  const [pick, setPick] = useState<PersonaPick>("");
  const [style, setStyle] = useState("");

  useEffect(() => {
    if (model.data?.model_profile_id) setPickedModel(model.data.model_profile_id);
  }, [model.data?.model_profile_id]);

  useEffect(() => {
    const cur = persona.data;
    if (!cur || !opts.data) return;
    if (cur.source === "preset") {
      setPick(`pre:${opts.data.presets.find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
    } else if (cur.source === "profile") {
      setPick(`my:${(mine.data ?? []).find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
    }
  }, [persona.data, opts.data, mine.data]);

  const problem = model.error ?? persona.error ?? models.error ?? opts.error;
  if (problem) {
    return (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось загрузить настройки ИИ-мастера: {(problem as Error).message}
      </div>
    );
  }

  if (!model.data || !persona.data || !models.data || !opts.data) {
    return (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Связываемся с нейросетевым терминалом мастера…
      </div>
    );
  }

  const m = model.data;
  const p = persona.data;

  const modelOptions: SelectOption[] = (models.data ?? []).map((x) => ({
    value: x.id,
    label: x.name,
    sublabel: `${PROVIDER_RU[x.provider] ?? x.provider} · ${x.resolved_model || x.model}`,
    badge: x.is_default ? "ОСНОВНАЯ" : PROVIDER_RU[x.provider]?.toUpperCase(),
    badgeTone: x.is_default ? ("accent" as const) : ("patina" as const),
  }));

  return (
    <div className="flex flex-col gap-6">
      {/* Current Model Configuration */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Нейросетевая модель мастера</h2>
          <div className="mt-1 flex items-center gap-2 font-mono text-xs text-muted">
            <span>Текущая модель:</span>
            <span className="text-accent font-semibold">
              {m.model_profile_name ? `${m.model_profile_name} · ` : ""}
              {PROVIDER_RU[m.provider] ?? m.provider} ({m.resolved_model || m.model})
            </span>
          </div>
        </div>

        {models.data.length === 0 ? (
          <p className="text-sm text-muted">
            Других настроенных моделей нет. Вы можете добавить новые в панели администратора.
          </p>
        ) : (
          <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3 pt-1">
            <div className="flex-1 min-w-0">
              <Field label="Сменить модель для стола">
                <CustomSelect
                  value={pickedModel}
                  options={modelOptions}
                  onChange={setPickedModel}
                  placeholder="Выберите модель..."
                  ariaLabel="Модель мастера"
                />
              </Field>
            </div>
            <ActionButton
              primary
              className="font-mono text-xs tracking-wider"
              run={async () => {
                if (!pickedModel) throw new Error("Выберите модель");
                if (pickedModel === m.model_profile_id) throw new Error("Эта модель уже активна за столом");
                qc.setQueryData(
                  ["master-model", campaignId],
                  await api<MasterModel>(`/api/campaigns/${campaignId}/master-model`, {
                    method: "PUT",
                    body: { model_profile_id: pickedModel },
                  }),
                );
              }}
              done="Модель переключится со следующего хода мастера"
            >
              ПРИМЕНИТЬ МОДЕЛЬ
            </ActionButton>
          </div>
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
        <PersonaEditor base={`/api/campaigns/${campaignId}/master-character`} master />
      </section>
    </div>
  );
}
