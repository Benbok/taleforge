import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field, Segmented } from "../components/Form";
import Header from "../components/Header";
import BriefForm from "../cabinet/BriefForm";
import PersonaPicker from "../cabinet/PersonaPicker";
import { api } from "../lib/api";
import {
  createBody,
  DIFFICULTY_RU,
  LEVELING_HINT,
  LEVELING_RU,
  EMPTY_DRAFT,
  loadDraft,
  saveDraft,
  stepProblems,
  WIZARD_STEPS,
  type CampaignDraft,
  type CampaignOptions,
  type MasterPreset,
  type Pack,
  type Persona,
  type PersonaPick,
  type PublishedModule,
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
  const [testScenes, setTestScenes] = useState<{ scene: string; situation: string; reply: string }[] | null>(null);
  useEffect(() => saveDraft(user.id, draft), [user.id, draft]);

  const admin = user.platform_role !== "player";
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options"), enabled: admin });
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => api<Pack[]>("/api/packs"), enabled: admin });
  const modules = useQuery({
    queryKey: ["published-modules"],
    queryFn: () => api<PublishedModule[]>("/api/modules"),
    enabled: admin,
  });
  const personas = useQuery({ queryKey: ["personas"], queryFn: () => api<Persona[]>("/api/me/master-personas"), enabled: admin });
  const presets = useQuery({ queryKey: ["master-presets"], queryFn: () => api<MasterPreset[]>("/api/me/master-presets"), enabled: admin });
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
  const fromBook = draft.source === "module";
  const book = fromBook ? modules.data?.find((m) => m.id === draft.module_id) : undefined;

  async function create() {
    const bad = WIZARD_STEPS.map((_, i) => stepProblems(draft, i)).flat();
    if (bad.length) throw new Error(bad.join("; "));
    const c = await api<Room>("/api/campaigns", { body: createBody(draft) });
    saveDraft(user.id, null);
    await qc.invalidateQueries({ queryKey: ["my-campaigns"] });
    if (draft.plan_now && !owner && !fromBook) {
      await api(`/api/campaigns/${c.id}/plan`, { body: {} }).catch((e: Error) =>
        toast.error(`Сюжет не запущен: ${e.message}`),
      );
    }
    navigate(`/c/${c.id}/manage`);
  }

  if (!admin) {
    return (
      <Shell>
        <div className="card border-bad/40 bg-bad/5 p-6 text-center">
          <h2 className="font-heading text-xl font-bold text-bad">Требуются права администратора</h2>
          <p className="mt-2 text-sm text-muted">
            Создавать новые кампании на платформе могут только администраторы.
            Попросите у ведущего или владельца стола ссылку-приглашение.
          </p>
          <div className="mt-4">
            <Link to="/" className="btn btn-outline-copper font-mono text-xs">
              Вернуться к моим играм
            </Link>
          </div>
        </div>
      </Shell>
    );
  }

  const loadError = opts.error ?? packs.error;
  if (loadError) {
    return (
      <Shell>
        <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
          Не удалось загрузить параметры кампаний: {(loadError as Error).message}
        </div>
      </Shell>
    );
  }

  if (!opts.data) {
    return (
      <Shell>
        <div className="card p-8 text-center text-muted font-mono text-sm">
          Инициализация конструктора кампании…
        </div>
      </Shell>
    );
  }

  // Options for World Pack select
  const packOptions: SelectOption[] = [
    {
      value: "",
      label: "Без пакета: базовые правила SRD 5.1",
      sublabel: "Классическое фэнтези, стандартные классы, расы и чудовища",
      badge: "SRD",
      badgeTone: "muted",
    },
    ...(packs.data ?? []).map((p) => ({
      value: p.id,
      label: p.name,
      sublabel: `Версия ${p.version} · уникальный лор, классы и бестиарий`,
      badge: `v${p.version}`,
      badgeTone: "accent" as const,
    })),
  ];

  // Options for Master model select
  const masterOptions: SelectOption[] = [
    {
      value: "ai",
      label: "ИИ-мастер (автоматически)",
      sublabel: "Сюжет и отыгрыш полностью генерируется нейросетью",
      badge: "AI",
      badgeTone: "accent",
    },
    {
      value: "owner",
      label: "Я веду сам (живой мастер)",
      sublabel: "Вы лично описываете сцены и бросаете вызовы игрокам за столом",
      badge: "HUMAN",
      badgeTone: "muted",
    },
  ];

  return (
    <Shell>
      {/* Wizard Steps Navigation Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-line pb-4">
        <nav aria-label="Шаги создания кампании" className="flex items-center gap-1.5 overflow-x-auto no-scrollbar">
          {WIZARD_STEPS.map((s, i) => {
            const isCurrent = i === draft.step;
            const isPassed = i < draft.step;
            return (
              <button
                key={s}
                type="button"
                aria-current={isCurrent ? "step" : undefined}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 font-mono text-xs transition ${
                  isCurrent
                    ? "border-accent bg-accent/15 text-accent font-semibold shadow-sm"
                    : isPassed
                      ? "border-patina/40 bg-patina/5 text-patina-hi hover:border-patina"
                      : "border-line bg-raised text-muted hover:border-line hover:text-ink"
                }`}
                onClick={() => go(i)}
              >
                <span>{isPassed ? "✓" : `${i + 1}.`}</span>
                <span>{s}</span>
              </button>
            );
          })}
        </nav>

        <div className="flex items-center gap-3 font-mono text-xs self-start sm:self-center">
          <span className="text-patina-hi flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-patina animate-pulse" />
            <span>{resumed ? "Черновик восстановлен" : "Автосохранение"}</span>
          </span>
          <button
            type="button"
            className="text-muted hover:text-bad transition underline text-[11px]"
            onClick={() => {
              if (window.confirm("Стереть сохранённый черновик и начать заново?")) setDraft(EMPTY_DRAFT);
            }}
          >
            сбросить
          </button>
        </div>
      </div>

      {/* Main Step Body Card */}
      <section className="card flex flex-col gap-5 p-5 sm:p-6 border border-line bg-surface shadow-xl">
        {draft.step === 0 && (
          <>
            <div>
              <h2 className="font-heading text-xl font-bold text-ink">Параметры экспедиции</h2>
              <p className="mt-0.5 text-xs text-muted">
                Название кампании, сеттинг мира и рекомендуемый размер партии
              </p>
            </div>

            <Field label="Название кампании">
              <input
                className="field font-heading text-lg"
                maxLength={128}
                placeholder="например: Тени над Затонувшим Архипелагом"
                value={draft.name}
                autoFocus
                onChange={(e) => set({ name: e.target.value })}
              />
            </Field>

            {(modules.data?.length ?? 0) > 0 && (
              <Field
                label="Сюжет"
                hint={
                  fromBook
                    ? "Мастер ведёт по книге: комнаты, проверки и сокровища берутся из приключения."
                    : "Сюжетную арку построит ИИ-архитектор по вашей анкете."
                }
              >
                <Segmented
                  label="Сюжет"
                  value={draft.source}
                  options={[
                    ["plot", "Свой сюжет"],
                    ["module", "Готовое приключение"],
                  ]}
                  onChange={(v) => set({ source: v as CampaignDraft["source"] })}
                />
              </Field>
            )}

            {fromBook ? (
              <ModulePick
                modules={modules.data ?? []}
                moduleId={draft.module_id}
                hookId={draft.module_hook}
                onChange={(patch) => set(patch)}
              />
            ) : (
              <Field
                label="Мир и сеттинг"
                hint="Пакет мира определяет лор, классы, чудовищ и оформление. При выборе базовых правил действует SRD 5.1."
              >
                <CustomSelect
                  value={draft.pack_id}
                  options={packOptions}
                  onChange={(val) => set({ pack_id: val, players: null })}
                  ariaLabel="Мир кампании"
                />
              </Field>
            )}

            <Field label="Уровень сложности вызовов">
              <Segmented
                label="Сложность"
                value={draft.difficulty}
                options={Object.entries(DIFFICULTY_RU)}
                onChange={(v) => set({ difficulty: v, players: null })}
              />
            </Field>

            {fromBook ? (
              <p className="text-xs text-muted">
                Рост уровней — по вехам книги: мастер поднимает уровень героям, когда отряд проходит этап приключения.
              </p>
            ) : (
              <Field label="Рост уровней" hint={LEVELING_HINT[draft.leveling]}>
                <Segmented
                  label="Рост уровней"
                  value={draft.leveling}
                  options={Object.entries(LEVELING_RU)}
                  onChange={(v) => set({ leveling: v as CampaignDraft["leveling"] })}
                />
              </Field>
            )}

            <Field
              label="Количество игроков за столом"
              hint={
                book?.party_size
                  ? `Приключение рассчитано на отряд из ${book.party_size}.`
                  : size.data
                    ? `Для выбранной сложности рекомендуется ${size.data.recommended} игроков (допустимо от ${size.data.min} до ${size.data.max}).`
                    : undefined
              }
            >
              <input
                className="field w-28 font-mono text-sm"
                type="number"
                min={1}
                max={6}
                value={draft.players ?? size.data?.recommended ?? 4}
                onChange={(e) => set({ players: Number(e.target.value) || null })}
              />
            </Field>
          </>
        )}

        {draft.step === 1 && (() => {
          const activePreset = presets.data?.find((p) => p.id === draft.master_preset_id);
          return (
            <>
              <div>
                <h2 className="font-heading text-xl font-bold text-ink">Ведущий и роль мастера</h2>
                <p className="mt-0.5 text-xs text-muted">
                  Выберите, кто будет вести кампанию — искусственный интеллект или живой мастер
                </p>
              </div>

              {presets.data && presets.data.length > 0 && (
                <Field
                  label="Готовый пресет мастера"
                  hint="Выберите сохранённую связку модели, тона и анкеты характера мастера, чтобы не настраивать с нуля."
                >
                  <CustomSelect
                    value={draft.master_preset_id ?? ""}
                    options={[
                      {
                        value: "",
                        label: "Без пресета (ручная настройка)",
                        sublabel: "Настроить модель и характер мастера ниже вручную",
                        badge: "ВРУЧНУЮ",
                        badgeTone: "muted",
                      },
                      ...presets.data.map((pr) => ({
                        value: pr.id,
                        label: pr.name,
                        sublabel: `${pr.model_profile_name ? `Модель: ${pr.model_profile_name}` : "Модель по умолчанию"}${pr.style_preview ? ` · «${pr.style_preview.slice(0, 45)}…»` : ""}`,
                        badge: "ПРЕСЕТ",
                        badgeTone: "patina" as const,
                      })),
                    ]}
                    onChange={(val) => {
                      setTestScenes(null);
                      if (!val) {
                        set({
                          master_preset_id: null,
                          master_style: "",
                          master_character: null,
                        });
                      } else {
                        const pr = presets.data?.find((p) => p.id === val);
                        if (pr) {
                          set({
                            master_preset_id: pr.id,
                            master: pr.model_profile_id ?? "",
                            persona: (pr.persona_preset
                              ? `pre:${pr.persona_preset}`
                              : pr.persona_id
                                ? `my:${pr.persona_id}`
                                : "") as PersonaPick,
                            master_style: pr.style ?? "",
                            master_character: pr.character ?? null,
                          });
                        }
                      }
                    }}
                    ariaLabel="Пресет мастера"
                  />
                </Field>
              )}

              {activePreset && !owner && (
                <div className="rounded-[10px] border border-patina/40 bg-patina/5 p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-heading text-sm font-bold text-ink">
                        Пресет «{activePreset.name}»
                      </span>
                      <span className="font-mono text-[10px] text-patina-hi px-1.5 py-0.5 rounded border border-patina/30 bg-patina/10">
                        АКТИВЕН
                      </span>
                    </div>
                    <button
                      type="button"
                      className="font-mono text-xs text-muted hover:text-bad underline"
                      onClick={() => {
                        setTestScenes(null);
                        set({
                          master_preset_id: null,
                          master_style: "",
                          master_character: null,
                        });
                      }}
                    >
                      сбросить пресет
                    </button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono text-muted">
                    <div>
                      <span className="text-ink">Модель: </span>
                      {activePreset.model_profile_name || "По умолчанию"}
                    </div>
                    {activePreset.style_preview && (
                      <div>
                        <span className="text-ink">Тон: </span>
                        {activePreset.style_preview}
                      </div>
                    )}
                  </div>
                  {activePreset.character?.text && (
                    <p className="text-xs text-muted italic font-serif border-t border-line/30 pt-1.5 mt-0.5 line-clamp-2">
                      «{activePreset.character.text}»
                    </p>
                  )}
                  {testScenes && testScenes.length > 0 ? (
                    <div className="mt-2 flex flex-col gap-2 border-t border-line/40 pt-2">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[11px] text-accent uppercase font-semibold">
                          Пробные сцены пресета:
                        </span>
                        <button
                          type="button"
                          className="text-xs font-mono text-muted hover:text-ink"
                          onClick={() => setTestScenes(null)}
                        >
                          ✕ Скрыть
                        </button>
                      </div>
                      {testScenes.map((s, idx) => (
                        <div key={idx} className="rounded border border-line bg-raised/50 p-2.5 text-xs">
                          <div className="font-mono text-[10px] text-accent font-semibold">{s.scene}</div>
                          <div className="text-muted mt-0.5">{s.situation}</div>
                          <div className="italic text-ink mt-1">«{s.reply}»</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="pt-1">
                      <ActionButton
                        className="font-mono text-xs px-2.5 py-1"
                        run={async () => {
                          const res = await api<{ scenes: { scene: string; situation: string; reply: string }[] }>(
                            "/api/me/master-presets/test",
                            {
                              method: "POST",
                              body: {
                                model_profile_id: activePreset.model_profile_id,
                                style: activePreset.style,
                                character: activePreset.character,
                              },
                            },
                          );
                          setTestScenes(res.scenes);
                        }}
                        done="Пробные сцены сгенерированы"
                      >
                        Проверить сцены мастера
                      </ActionButton>
                    </div>
                  )}
                </div>
              )}

            <Field
              label="Кто ведёт приключение"
              hint="Нейросеть генерирует сюжет по вашим параметрам, или вы лично описываете сцены."
            >
              <CustomSelect
                value={draft.master}
                options={masterOptions}
                onChange={(val) => set({ master: val })}
                ariaLabel="Ведущий игры"
              />
            </Field>

            {!owner && (
              <>
                <Field
                  label="Характер и стиль повествования мастера"
                  hint="Определяет тон нарратива, юмор и манеру описания сцен. Игровые правила остаются каноничными."
                >
                  <PersonaPicker
                    value={draft.persona}
                    onChange={(persona) => set({ persona })}
                    opts={opts.data}
                    mine={personas.data ?? []}
                  />
                </Field>

                <label className="flex items-center gap-2.5 text-sm cursor-pointer py-1">
                  <input
                    type="checkbox"
                    className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                    checked={draft.owner_plays}
                    onChange={(e) => set({ owner_plays: e.target.checked })}
                  />
                  <span className="font-medium text-ink">Я тоже играю: сразу занять свободное место игрока за столом</span>
                </label>
              </>
            )}

            <Field
              label="Режим проверки персонажей"
              hint="Мастером — ведущий изучает биографию и связывает её с сюжетом. Автоматически — лист сразу допускается в игру при корректности правил."
            >
              <Segmented
                label="Проверка героев"
                value={draft.review}
                options={[
                  ["master", "Проверка мастером"],
                  ["auto", "Автоматический допуск"],
                ]}
                onChange={(review) => set({ review })}
              />
            </Field>
          </>
        );
      })()}

        {draft.step === 2 && (
          <>
            <div>
              <h2 className="font-heading text-xl font-bold text-ink">Анкета приключения</h2>
              <p className="mt-0.5 text-xs text-muted">
                Ожидания игроков по длительности, балансу боёв и исследований. Всё необязательно — незаполненное архитектор сбалансирует сам.
              </p>
            </div>

            {fromBook ? (
              <p className="rounded-[10px] border border-line bg-raised/50 p-3.5 text-sm text-muted">
                Сюжет, места и противники берутся из приключения «{book?.title ?? "…"}», анкета архитектору не нужна.
                Запретные темы мастер всё равно обойдёт.
              </p>
            ) : (
              <BriefForm brief={draft.brief} opts={opts.data.brief} onChange={(brief) => set({ brief })} />
            )}

            <Field label="Запретные темы и триггеры" hint="Укажите через запятую: мастер и генератор сюжета гарантированно обойдут их стороной.">
              <input
                className="field text-sm"
                placeholder="например: пауки, пытки, гибель детей"
                value={draft.excluded}
                onChange={(e) => set({ excluded: e.target.value })}
              />
            </Field>
          </>
        )}

        {draft.step === 3 && (
          <>
            <div>
              <h2 className="font-heading text-xl font-bold text-ink">Сюжетная вводная и запуск</h2>
              <p className="mt-0.5 text-xs text-muted">
                Финальная проверка параметров перед созданием кампании
              </p>
            </div>

            <Field
              label="Публичное вступление (афиша стола)"
              hint={
                fromBook
                  ? "Можно оставить пустым: возьмём завязку из книги."
                  : owner
                    ? "Её увидят приглашённые игроки."
                    : "Можно оставить пустым: вводную подготовит ИИ-архитектор сюжета."
              }
            >
              <textarea
                className="field min-h-24 text-sm"
                maxLength={10000}
                placeholder="В туманной гавани у маяка собираются смельчаки, откликнувшиеся на зов гильдии..."
                value={draft.public_intro}
                onChange={(e) => set({ public_intro: e.target.value })}
              />
            </Field>

            {!owner && !fromBook && (
              <label className="flex items-start gap-2.5 rounded-[10px] border border-accent/40 bg-accent/10 p-3.5 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-[var(--tf-accent)] mt-1 h-4 w-4 rounded"
                  checked={draft.plan_now}
                  onChange={(e) => set({ plan_now: e.target.checked })}
                />
                <div className="flex flex-col gap-0.5">
                  <span className="font-medium text-ink">Сразу сгенерировать сюжетную арку приключения</span>
                  <span className="text-xs text-muted leading-relaxed">
                    Архитектор создаст завязку, антагонистов с их планом угрозы, узлы актов и тайны. Запуск занимает пару минут в фоне.
                  </span>
                </div>
              </label>
            )}

            <div>
              <h3 className="font-heading text-base font-bold text-ink mb-2">Формуляр создаваемой кампании:</h3>
              <Summary draft={draft} opts={opts.data} packs={packs.data ?? []} book={book} />
            </div>
          </>
        )}
      </section>

      {/* Navigation Footer Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <button
          type="button"
          className="btn font-mono text-xs"
          disabled={draft.step === 0}
          onClick={() => go(draft.step - 1)}
        >
          ← НАЗАД
        </button>

        {draft.step < WIZARD_STEPS.length - 1 ? (
          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              className="btn btn-primary font-mono text-xs tracking-wider"
              disabled={problems.length > 0}
              onClick={() => go(draft.step + 1)}
            >
              ДАЛЕЕ →
            </button>
            {problems.length > 0 && <span className="font-mono text-xs text-warn">{problems.join("; ")}</span>}
          </div>
        ) : (
          <ActionButton
            primary
            className="font-mono text-xs tracking-wider"
            run={create}
            done="Кампания успешно создана"
          >
            СОЗДАТЬ КАМПАНИЮ И ОТКРЫТЬ КАБИНЕТ →
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
        <Link
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          to="/"
          aria-label="К списку столов"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>
      </Header>

      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Судовая верфь · Подготовка экспедиции</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                Новая кампания
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Конфигурация игрового стола: мир, модель ведущего, правила проверки и сюжетная канва.
              </p>
            </div>
          </div>
        </div>

        {children}
      </main>
    </>
  );
}

function Summary({
  draft,
  opts,
  packs,
  book,
}: {
  draft: CampaignDraft;
  opts: CampaignOptions;
  packs: Pack[];
  book?: PublishedModule;
}) {
  const master =
    draft.master === "owner"
      ? "Владелец кампании (живой мастер)"
      : "ИИ-мастер";
  const persona = draft.persona.startsWith("pre:")
    ? opts.presets.find((p) => p.id === draft.persona.slice(4))?.name
    : draft.persona
      ? "Своя персона"
      : null;
  const b = draft.brief;
  const hook = book?.hooks.find((h) => h.id === draft.module_hook)?.title ?? book?.hooks[0]?.title;
  const rows: [string, string][] = [
    ["Название стола", draft.name || "—"],
    book
      ? ["Готовое приключение", `«${book.title}»` + (hook ? `, зацепка «${hook}»` : "")]
      : ["Сеттинг / Пакет", packs.find((p) => p.id === draft.pack_id)?.name ?? "Базовые правила (SRD 5.1)"],
    ["Сложность", DIFFICULTY_RU[draft.difficulty] ?? draft.difficulty],
    ["Рост уровней", book ? "По вехам книги" : (LEVELING_RU[draft.leveling] ?? draft.leveling)],
    ["Ведущий", master + (persona && draft.master !== "owner" ? ` (${persona})` : "")],
    ...((book
      ? []
      : [
          ["Длительность", b.length ? opts.brief.length[b.length] : "На усмотрение архитектора"],
          ["Атмосфера", b.emotions?.length ? b.emotions.map((e) => opts.brief.emotions[e]).join(", ") : "Стандартная"],
        ]) as [string, string][]),
  ];

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 rounded-[10px] border border-line bg-raised/50 p-4 text-xs sm:text-sm font-mono">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}:</dt>
          <dd className="font-semibold text-accent">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Выбор приключения из библиотеки и зацепки, с которой герои войдут в историю. */
function ModulePick({
  modules,
  moduleId,
  hookId,
  onChange,
}: {
  modules: PublishedModule[];
  moduleId: string;
  hookId: string;
  onChange: (patch: Partial<CampaignDraft>) => void;
}) {
  const book = modules.find((m) => m.id === moduleId);
  const options: SelectOption[] = modules.map((m) => {
    const lv = m.levels?.start ? `уровни ${m.levels.start}–${m.levels.end ?? m.levels.start}` : "";
    const maps = m.maps ? `карт: ${m.maps}` : "без карт";
    return { value: m.id, label: m.title, sublabel: [lv, maps].filter(Boolean).join(" · "), badge: "КНИГА", badgeTone: "accent" as const };
  });
  const chosen = book?.hooks.find((h) => h.id === hookId) ?? book?.hooks[0];
  return (
    <>
      <Field label="Приключение" hint={book?.summary || "Опубликованные приключения из админки, вкладка «Готовые приключения»."}>
        <CustomSelect
          value={moduleId}
          options={[{ value: "", label: "Выберите приключение" }, ...options]}
          onChange={(val) => onChange({ module_id: val, module_hook: "", players: null })}
          ariaLabel="Готовое приключение"
        />
      </Field>
      {book && book.hooks.length > 0 && (
        <Field label="Как герои вступают в историю" hint="Зацепка из книги: с неё начнётся вступление.">
          <div className="flex flex-col gap-2" role="radiogroup" aria-label="Зацепка">
            {book.hooks.map((h) => (
              <label
                key={h.id}
                className={`flex cursor-pointer items-start gap-2.5 rounded-[10px] border p-3 text-sm transition ${
                  chosen?.id === h.id ? "border-accent bg-accent/10" : "border-line bg-raised/50 hover:border-accent/50"
                }`}
              >
                <input
                  type="radio"
                  name="module-hook"
                  className="mt-1 accent-[var(--tf-accent)]"
                  checked={chosen?.id === h.id}
                  onChange={() => onChange({ module_hook: h.id })}
                />
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium text-ink">{h.title}</span>
                  <span className="text-xs text-muted leading-relaxed">{h.text}</span>
                </span>
              </label>
            ))}
          </div>
        </Field>
      )}
    </>
  );
}
