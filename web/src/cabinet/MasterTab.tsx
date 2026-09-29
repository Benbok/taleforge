import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import PersonaPicker from "./PersonaPicker";
import { api } from "../lib/api";
import { personaBody, PROVIDER_RU, type CampaignOptions, type ModelProfile, type Persona, type PersonaPick } from "../lib/campaign";

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
  const model = useQuery({ queryKey: ["master-model", campaignId], queryFn: () => api<MasterModel>(`/api/campaigns/${campaignId}/master-model`) });
  const persona = useQuery({ queryKey: ["master-persona", campaignId], queryFn: () => api<CampaignPersona>(`/api/campaigns/${campaignId}/master-persona`) });
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
    // текущий выбор узнаём по имени: кампания хранит копию персоны, а не ссылку
    if (cur.source === "preset") setPick(`pre:${opts.data.presets.find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
    else if (cur.source === "profile") setPick(`my:${(mine.data ?? []).find((p) => p.name === cur.name)?.id ?? ""}` as PersonaPick);
  }, [persona.data, opts.data, mine.data]);

  const problem = model.error ?? persona.error ?? models.error ?? opts.error;
  if (problem) return <p className="text-bad">Не удалось загрузить: {(problem as Error).message}</p>;
  if (!model.data || !persona.data || !models.data || !opts.data) return <p className="text-muted">Загружаем…</p>;
  const m = model.data;
  const p = persona.data;

  return (
    <div className="flex flex-col gap-5">
      <section className="card flex flex-col gap-3 p-4">
        <h2 className="text-base font-semibold">Модель</h2>
        <p className="text-sm text-muted">
          Сейчас: {m.model_profile_name ? `${m.model_profile_name} · ` : ""}
          {PROVIDER_RU[m.provider] ?? m.provider} · {m.resolved_model || m.model}
        </p>
        {models.data.length === 0 ? (
          <p className="text-sm text-muted">Других моделей нет. Их добавляют в профиле, в разделе «Модели ИИ».</p>
        ) : (
          <div className="flex flex-wrap items-start gap-2">
            <select className="field min-w-0 flex-1" aria-label="Модель мастера" value={pickedModel} onChange={(e) => setPickedModel(e.target.value)}>
              <option value="" disabled>
                Выберите модель
              </option>
              {models.data.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                  {x.is_default ? " (по умолчанию)" : ""} · {PROVIDER_RU[x.provider]}
                </option>
              ))}
            </select>
            <ActionButton
              primary
              run={async () => {
                if (!pickedModel) throw new Error("Выберите модель");
                if (pickedModel === m.model_profile_id) throw new Error("Эта модель уже ведёт кампанию");
                qc.setQueryData(["master-model", campaignId], await api<MasterModel>(`/api/campaigns/${campaignId}/master-model`, { method: "PUT", body: { model_profile_id: pickedModel } }));
              }}
              done="Модель сменится со следующего хода мастера"
            >
              Сменить модель
            </ActionButton>
          </div>
        )}
      </section>

      <section className="card flex flex-col gap-3 p-4">
        <h2 className="text-base font-semibold">Характер мастера</h2>
        <p className="whitespace-pre-line text-sm text-muted">
          Сейчас: {p.name ?? (p.source === "custom" ? "своя настройка" : p.style ? p.style : "мастер по умолчанию")}
        </p>
        <PersonaPicker value={pick} onChange={setPick} opts={opts.data} mine={mine.data ?? []} />
        <Field label="Дополнить своими словами" hint="Например «говорит медленно, любит старые поговорки».">
          <textarea className="field min-h-14" maxLength={2000} value={style} onChange={(e) => setStyle(e.target.value)} />
        </Field>
        <div>
          <ActionButton
            primary
            run={async () => {
              qc.setQueryData(
                ["master-persona", campaignId],
                await api<CampaignPersona>(`/api/campaigns/${campaignId}/master-persona`, {
                  method: "PUT",
                  body: { ...personaBody(pick), style: style.trim() || null },
                }),
              );
            }}
            done="Новый тон — со следующего хода мастера"
          >
            Сменить характер
          </ActionButton>
        </div>
      </section>
    </div>
  );
}
