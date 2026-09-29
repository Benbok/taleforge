import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import { Field, Segmented } from "../components/Form";
import Header from "../components/Header";
import BriefForm from "../cabinet/BriefForm";
import PersonaPicker from "../cabinet/PersonaPicker";
import { api } from "../lib/api";
import {
  createBody,
  DIFFICULTY_RU,
  EMPTY_DRAFT,
  loadDraft,
  saveDraft,
  stepProblems,
  WIZARD_STEPS,
  type CampaignDraft,
  type CampaignOptions,
  type ModelProfile,
  type Pack,
  type Persona,
  type Room,
} from "../lib/campaign";
import { useSession } from "../stores/session";
import { toast } from "../stores/toasts";

/** Новая кампания по шагам. Черновик сохраняется в браузере на каждом изменении: можно уйти и вернуться. */
export default function NewCampaignPage() {
  const user = useSession((s) => s.user)!;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<CampaignDraft>(() => loadDraft(user.id) ?? EMPTY_DRAFT);
  const [resumed] = useState(() => !!loadDraft(user.id));
  useEffect(() => saveDraft(user.id, draft), [user.id, draft]);

  const admin = user.platform_role !== "player";
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options"), enabled: admin });
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => api<Pack[]>("/api/packs"), enabled: admin });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<ModelProfile[]>("/api/admin/models"), enabled: admin });
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas"), enabled: admin });
  const size = useQuery({
    queryKey: ["party-size", draft.difficulty, draft.pack_id],
    queryFn: () =>
      api<{ recommended: number; min: number; max: number }>(
        `/api/party-size?difficulty=${draft.difficulty}${draft.pack_id ? `&pack_id=${encodeURIComponent(draft.pack_id)}` : ""}`,
      ),
    enabled: admin,
  });

  const set = (patch: Partial<CampaignDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const go = (step: number) => set({ step: Math.max(0, Math.min(WIZARD_STEPS.length - 1, step)) });
  const problems = stepProblems(draft, draft.step);
  const owner = draft.master === "owner";

  async function create() {
    const bad = WIZARD_STEPS.map((_, i) => stepProblems(draft, i)).flat();
    if (bad.length) throw new Error(bad.join("; "));
    const c = await api<Room>("/api/campaigns", { body: createBody(draft) });
    saveDraft(user.id, null);
    await qc.invalidateQueries({ queryKey: ["my-campaigns"] });
    if (draft.plan_now && !owner) {
      // сюжет готовится в фоне; не вышло запустить — кампания всё равно создана, запустить можно из кабинета
      await api(`/api/campaigns/${c.id}/plan`, { body: {} }).catch((e: Error) => toast.error(`Сюжет не запущен: ${e.message}`));
    }
    navigate(`/c/${c.id}/manage`);
  }

  if (!admin)
    return (
      <Shell>
        <p className="card p-5">Создавать кампании могут администраторы. Попросите у владельца кампании ссылку-приглашение.</p>
      </Shell>
    );
  const loadError = opts.error ?? models.error ?? packs.error;
  if (loadError)
    return (
      <Shell>
        <p className="text-bad">Не удалось загрузить варианты: {(loadError as Error).message}</p>
      </Shell>
    );
  if (!opts.data || !models.data)
    return (
      <Shell>
        <p className="text-muted">Загружаем…</p>
      </Shell>
    );

  const defModel = models.data.find((m) => m.is_default);
  return (
    <Shell>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <nav aria-label="Шаги" className="flex flex-wrap gap-1.5">
          {WIZARD_STEPS.map((s, i) => (
            <button
              key={s}
              aria-current={i === draft.step ? "step" : undefined}
              className={`rounded-full border px-3 py-1 text-sm ${i === draft.step ? "border-accent text-ink" : "border-line text-muted"}`}
              onClick={() => go(i)}
            >
              {i + 1}. {s}
            </button>
          ))}
        </nav>
        <span className="flex items-center gap-2 text-xs text-muted">
          {resumed ? "Черновик восстановлен" : "Черновик сохраняется сам"}
          <button
            className="underline"
            onClick={() => {
              if (window.confirm("Стереть черновик и начать заново?")) setDraft(EMPTY_DRAFT);
            }}
          >
            начать заново
          </button>
        </span>
      </div>

      <section className="card flex flex-col gap-4 p-5">
        {draft.step === 0 && (
          <>
            <Field label="Название">
              <input className="field" maxLength={128} value={draft.name} autoFocus onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field label="Мир" hint="Пакет мира задаёт лор, классы, происхождения и чудовищ. Без пакета — базовые правила SRD.">
              <select className="field" value={draft.pack_id} onChange={(e) => set({ pack_id: e.target.value, players: null })}>
                <option value="">Без пакета: базовые правила</option>
                {(packs.data ?? []).map((p) => (
                  <option key={`${p.id}@${p.version}`} value={p.id}>
                    {p.name} {p.version}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Сложность">
              <Segmented
                label="Сложность"
                value={draft.difficulty}
                options={Object.entries(DIFFICULTY_RU)}
                onChange={(v) => set({ difficulty: v, players: null })}
              />
            </Field>
            <Field
              label="Игроков"
              hint={size.data ? `Для этой сложности рекомендуется ${size.data.recommended}, можно от ${size.data.min} до ${size.data.max}.` : undefined}
            >
              <input
                className="field w-24"
                type="number"
                min={1}
                max={6}
                value={draft.players ?? size.data?.recommended ?? 4}
                onChange={(e) => set({ players: Number(e.target.value) || null })}
              />
            </Field>
          </>
        )}

        {draft.step === 1 && (
          <>
            <Field
              label="Кто ведёт игру"
              hint={models.data.length ? undefined : "Моделей ИИ ещё нет: будет Claude по умолчанию. Свои модели настраиваются в профиле."}
            >
              <select className="field" value={draft.master} onChange={(e) => set({ master: e.target.value })}>
                <option value="">ИИ-мастер: {defModel ? `${defModel.name} (по умолчанию)` : "модель по умолчанию"}</option>
                {models.data
                  .filter((m) => !m.is_default)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      ИИ-мастер: {m.name}
                    </option>
                  ))}
                <option value="owner">Я веду сам</option>
              </select>
            </Field>
            {!owner && (
              <>
                <Field label="Характер мастера" hint="Тон, юмор и манера подачи. Механику и сложность не меняет. Свои персоны — в профиле.">
                  <PersonaPicker value={draft.persona} onChange={(persona) => set({ persona })} opts={opts.data} mine={personas.data ?? []} />
                </Field>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={draft.owner_plays} onChange={(e) => set({ owner_plays: e.target.checked })} />
                  Я тоже играю: сразу занять место игрока
                </label>
              </>
            )}
            <Field label="Проверка героев" hint="Мастер читает историю героя и может тайно связать её с сюжетом. Автоматически — сразу в игру, если лист собран по правилам.">
              <Segmented
                label="Проверка героев"
                value={draft.review}
                options={[
                  ["master", "Мастером"],
                  ["auto", "Автоматически"],
                ]}
                onChange={(review) => set({ review })}
              />
            </Field>
          </>
        )}

        {draft.step === 2 && (
          <>
            <BriefForm brief={draft.brief} opts={opts.data.brief} onChange={(brief) => set({ brief })} />
            <Field label="Запретные темы" hint="Через запятую. Мастер их не коснётся.">
              <input className="field" value={draft.excluded} onChange={(e) => set({ excluded: e.target.value })} />
            </Field>
          </>
        )}

        {draft.step === 3 && (
          <>
            <Field label="Публичная вводная" hint={owner ? "Её увидят игроки по приглашению." : "Можно оставить пустой: её напишет архитектор сюжета."}>
              <textarea className="field min-h-28" maxLength={10000} value={draft.public_intro} onChange={(e) => set({ public_intro: e.target.value })} />
            </Field>
            {!owner && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={draft.plan_now} onChange={(e) => set({ plan_now: e.target.checked })} />
                <span>
                  Сразу подготовить сюжет: завязку, злодеев, акты, места и тайны.
                  <span className="block text-xs text-muted">Идёт в фоне несколько минут. Другой вариант можно заказать в кабинете, пока игра не началась.</span>
                </span>
              </label>
            )}
            <Summary draft={draft} models={models.data} opts={opts.data} packs={packs.data ?? []} />
          </>
        )}
      </section>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <button className="btn" disabled={draft.step === 0} onClick={() => go(draft.step - 1)}>
          ← Назад
        </button>
        {draft.step < WIZARD_STEPS.length - 1 ? (
          <span className="flex flex-col items-end gap-1">
            <button className="btn btn-primary" disabled={problems.length > 0} onClick={() => go(draft.step + 1)}>
              Далее →
            </button>
            {problems.length > 0 && <span className="text-xs text-warn">{problems.join("; ")}</span>}
          </span>
        ) : (
          <ActionButton primary run={create} done="Кампания создана">
            Создать кампанию
          </ActionButton>
        )}
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Header>
        <Link className="btn px-3 py-1" to="/" aria-label="К кампаниям">
          ←<span className="hidden sm:inline"> Кампании</span>
        </Link>
      </Header>
      <main className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6">
        <h1 className="text-2xl font-semibold">Новая кампания</h1>
        {children}
      </main>
    </>
  );
}

function Summary({ draft, models, opts, packs }: { draft: CampaignDraft; models: ModelProfile[]; opts: CampaignOptions; packs: Pack[] }) {
  const master =
    draft.master === "owner" ? "вы сами" : `ИИ, ${models.find((m) => m.id === draft.master)?.name ?? models.find((m) => m.is_default)?.name ?? "модель по умолчанию"}`;
  const persona = draft.persona.startsWith("pre:") ? opts.presets.find((p) => p.id === draft.persona.slice(4))?.name : draft.persona ? "своя" : null;
  const b = draft.brief;
  const rows: [string, string][] = [
    ["Название", draft.name || "—"],
    ["Мир", packs.find((p) => p.id === draft.pack_id)?.name ?? "базовые правила"],
    ["Сложность", DIFFICULTY_RU[draft.difficulty]],
    ["Мастер", master + (persona && draft.master !== "owner" ? ` · ${persona}` : "")],
    ["Длительность", b.length ? opts.brief.length[b.length] : "решит мастер"],
    ["Эмоции", b.emotions?.length ? b.emotions.map((e) => opts.brief.emotions[e]).join(", ") : "решит мастер"],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-md border border-line p-3 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
