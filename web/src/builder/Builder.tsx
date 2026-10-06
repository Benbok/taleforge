import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";
import {
  builderUrls,
  draftFrom,
  emptyDraft,
  equipFor,
  groupOptions,
  METHOD_HINT,
  METHOD_RU,
  partLabel,
  pointsSpent,
  poolLeft,
  spellNeed,
  steps,
  toBody,
  weaponSlots,
  weaponsOf,
  withMethod,
  type BuilderMode,
  type BuilderOptions,
  type Draft,
  type Method,
  type OriginOption,
  type Preview,
  type SavedHero,
} from "../lib/builder";
import { ABILITIES, ABILITY_ABBR, ABILITY_RU, SKILLS, signed } from "../game/hero";
import { SKILL_DETAILS } from "../game/statDetails";
import CustomSelect from "../components/CustomSelect";
import ClassChoices from "./ClassChoices";
import LiveSheet from "./LiveSheet";
import OriginChoices from "./OriginChoices";
import SpellChoices from "./SpellChoices";
import { StatDetailTrigger } from "./StatDetailPopover";

const SKILL_RU = Object.fromEntries(SKILLS.map(([id, ru]) => [id, ru]));

const TITLES: Record<BuilderMode, { save: string; saved: string }> = {
  campaign: { save: "Сохранить черновик", saved: "Черновик сохранён" },
  premade: { save: "Сохранить заготовку", saved: "Заготовка сохранена" },
  library: { save: "Сохранить в библиотеку", saved: "Герой сохранён в библиотеке" },
};

const STEP_GUIDE: Record<string, { subtitle: string; hint: string }> = {
  name: {
    subtitle: "Имя или позывной",
    hint: "Придумайте имя персонажа, под которым его будут знать союзники и враги.",
  },
  class: {
    subtitle: "Боевое призвание",
    hint: "Класс определяет вашу боевую роль, кость хитов, владение оружием и спасброски. Наведите на карточку или нажмите «i», чтобы увидеть особенности.",
  },
  origin: {
    subtitle: "Наследие и корни",
    hint: "Происхождение даёт прибавки к характеристикам и врождённые черты. Наведите на карточку или нажмите «i», чтобы увидеть подробности.",
  },
  abilities: {
    subtitle: "Сила, ловкость и разум",
    hint: "Распределите ключевые показатели характеристик персонажа. Учитывайте ключевые параметры выбранного класса.",
  },
  spells: {
    subtitle: "Формулы, молитвы и договоры",
    hint: "Выберите заговоры и заклинания героя. Наведите на заклинание или нажмите «i», чтобы прочитать, что оно делает.",
  },
  skills: {
    subtitle: "Мастерство и тренировка",
    hint: "Выберите навыки, в которых персонаж обучен — они добавляют бонус мастерства к соответствующим проверкам.",
  },
  gear: {
    subtitle: "Оружие и снаряжение",
    hint: "Сформируйте начальный боекомплект и вооружение из доступных опций вашего класса.",
  },
  story: {
    subtitle: "Внешность и личная тайна",
    hint: "Опишите внешность для сопартийцев и потаённую тайну персонажа, о которой будет знать только ведущий игры.",
  },
};

/** Конструктор героя: слева выбор по шагам, справа живой лист, который считает сервер по правилам кампании. */
export default function Builder({
  mode,
  campaignId,
  opts,
  hero,
  onSaved,
  onSubmitted,
  packId,
  asSeat,
}: {
  mode: BuilderMode;
  campaignId?: string;
  /** Мир героя профиля: null — базовые правила. Кампания берёт мир из своих настроек. */
  packId?: string | null;
  asSeat?: string;
  opts: BuilderOptions;
  hero: SavedHero | null;
  onSaved: (h: SavedHero) => void;
  onSubmitted?: (status: string) => void;
}) {
  const methods = opts.ability_methods.filter((m) => mode !== "premade" || m !== "roll");
  const [draft, setDraft] = useState<Draft>(() => {
    const d = hero ? draftFrom(hero, opts) : emptyDraft(opts);
    const withMethodOk = methods.includes(d.ability_method) ? d : withMethod(d, methods[0] ?? "standard_array");
    const cls = opts.classes.find((c) => c.id === withMethodOk.class_id);
    return { ...withMethodOk, equipment_choices: equipFor(cls, withMethodOk.equipment_choices, opts) };
  });
  const [rolls, setRolls] = useState<number[] | null>(
    ((hero?.sheet as Record<string, unknown> | undefined)?.ability_rolls as number[] | undefined) ?? null,
  );
  const [saved, setSaved] = useState<SavedHero | null>(hero);
  const urls = builderUrls(mode, campaignId, saved?.id, asSeat);
  const cls = opts.classes.find((c) => c.id === draft.class_id);
  const origin = opts.origins.find((o) => o.id === draft.origin_id);
  const extra = useMemo(() => (mode === "library" ? { pack_id: packId ?? "" } : {}), [mode, packId]);
  const preview = usePreview(urls.preview, draft, rolls, extra);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setAbility = (a: string, v: number | null) =>
    setDraft((d) => ({ ...d, abilities: { ...d.abilities, [a]: v } }));

  /** Сохраняет черновик и возвращает героя, не уведомляя родителя (не вызывает navigate). */
  async function _saveToApi(body: Record<string, unknown>): Promise<SavedHero> {
    const obj = await api<SavedHero>(urls.save, { method: saved ? "PUT" : "POST", body });
    setSaved(obj);
    return obj;
  }

  async function save(): Promise<SavedHero> {
    const obj = await _saveToApi({ ...toBody(draft, rolls), ...extra });
    onSaved(obj);
    return obj;
  }

  async function roll() {
    // Сначала получаем id (сохраняем без уведомления родителя, чтобы navigate не убил компонент).
    const obj = saved ?? (await _saveToApi({ ...toBody(draft, rolls), ...extra }));
    const rollUrl = builderUrls(mode, campaignId, obj.id, asSeat).roll!;
    const r = await api<{ rolls: number[] }>(rollUrl, { method: "POST" });
    setRolls(r.rolls);
    setDraft((d) => ({ ...d, abilities: Object.fromEntries(ABILITIES.map((a) => [a, null])) }));
    // Уведомляем родителя только после броска — navigate произойдёт тут, с уже обновлённым состоянием.
    onSaved(obj);
  }

  async function submit() {
    const obj = await save();
    if (obj.errors?.length) throw new Error(`Не хватает: ${obj.errors.join("; ")}`);
    const r = await api<{ status: string; errors: string[] }>(builderUrls(mode, campaignId, obj.id, asSeat).submit!, {
      method: "POST",
    });
    if (r.errors.length) throw new Error(r.errors.join("; "));
    onSubmitted?.(r.status);
  }

  const st = steps(draft, opts, preview.data);
  const at = (id: string) => Math.max(0, st.findIndex((x) => x.id === id));
  const sn = spellNeed(cls, preview.data);
  const skillNeed = cls?.skills_choose?.count ?? 0;
  const skillFrom = cls?.skills_choose?.from?.length ? cls.skills_choose.from : SKILLS.map(([id]) => id);
  const expertNeed = cls?.expertise ?? 0;
  // компетентность — только в навыках, которыми герой владеет: выбранных в классе и данных происхождением
  const expertFrom = [...new Set([...(origin?.proficiencies?.skills ?? []), ...draft.skills])];

  const [activeStep, setActiveStep] = useState<string>("name");
  const [wizardMode, setWizardMode] = useState<boolean>(true);

  const currentIdx = Math.max(0, st.findIndex((s) => s.id === activeStep));
  const prevStep = currentIdx > 0 ? st[currentIdx - 1] : null;
  const nextStep = currentIdx < st.length - 1 ? st[currentIdx + 1] : null;

  const goToStep = (id: string) => {
    setActiveStep(id);
    if (!wizardMode) {
      document.getElementById(`step-${id}`)?.scrollIntoView({ behavior: "smooth" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const goNext = () => {
    if (nextStep) goToStep(nextStep.id);
  };

  const goPrev = () => {
    if (prevStep) goToStep(prevStep.id);
  };

  const renderFooter = (stepIdx: number) => {
    const isFirst = stepIdx === 0;
    const isLast = stepIdx === st.length - 1;
    const prev = isFirst ? null : st[stepIdx - 1];
    const next = isLast ? null : st[stepIdx + 1];

    return (
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-line/50">
        <div className="flex items-center gap-2">
          {prev ? (
            <button
              type="button"
              onClick={goPrev}
              className="btn border-line bg-raised/50 px-3.5 py-1.5 font-mono text-xs text-muted hover:text-ink hover:border-line cursor-pointer"
            >
              ← Назад ({prev.label})
            </button>
          ) : (
            <span />
          )}

          <ActionButton
            run={save}
            done={TITLES[mode].saved}
            primary={false}
            className="font-mono text-xs tracking-wider"
          >
            {TITLES[mode].save.toUpperCase()}
          </ActionButton>
        </div>

        <div className="flex items-center gap-2">
          {next ? (
            <button
              type="button"
              onClick={goNext}
              className="btn btn-primary px-4 py-1.5 font-mono text-xs tracking-wider cursor-pointer"
            >
              Далее: {next.label} →
            </button>
          ) : mode === "campaign" ? (
            <ActionButton
              run={submit}
              primary
              done="Герой отправлен мастеру на проверку"
              className="font-mono text-xs tracking-wider"
            >
              ОТПРАВИТЬ МАСТЕРУ НА ПРОВЕРКУ →
            </ActionButton>
          ) : (
            <ActionButton
              run={save}
              done={TITLES[mode].saved}
              primary
              className="font-mono text-xs tracking-wider"
            >
              {TITLES[mode].save.toUpperCase()}
            </ActionButton>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="grid gap-6 pb-16 lg:grid-cols-[minmax(0,1fr)_23rem] lg:pb-0">
      <div className="flex min-w-0 flex-col gap-6">
        {/* Step Navigation Bar */}
        <div className="flex flex-col gap-3 rounded-[12px] border border-line bg-surface p-3.5 shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b border-line/50 pb-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold uppercase tracking-wider text-accent">
                {wizardMode ? `Шаг ${currentIdx + 1} из ${st.length}` : "Все разделы"}
              </span>
              <span className="text-muted text-xs">·</span>
              <span className="font-heading text-sm font-bold text-ink">
                {wizardMode ? st[currentIdx]?.label : "Конструктор героя"}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setWizardMode((v) => !v)}
              className="btn px-2.5 py-1 text-[11px] font-mono text-muted hover:text-ink border-line cursor-pointer"
              title={wizardMode ? "Переключиться на просмотр всех шагов сразу" : "Переключиться на пошаговый мастер"}
            >
              {wizardMode ? "Показать всё разом" : "Пошаговый режим"}
            </button>
          </div>

          <nav
            aria-label="Шаги создания героя"
            className={`grid grid-cols-4 gap-1.5 ${st.length > 7 ? "sm:grid-cols-8" : "sm:grid-cols-7"}`}
          >
            {st.map((s, idx) => {
              const isActive = s.id === activeStep && wizardMode;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => goToStep(s.id)}
                  className={`flex items-center justify-center gap-1.5 rounded-[8px] py-1.5 px-2 text-xs font-mono transition cursor-pointer border ${
                    isActive
                      ? "border-accent bg-accent/15 text-accent font-bold shadow-sm"
                      : s.done
                      ? "border-patina/40 bg-patina/10 text-patina-hi hover:border-patina/70"
                      : "border-line bg-raised/40 text-muted hover:border-line hover:text-ink"
                  }`}
                >
                  <span className="text-[10px] opacity-80">{s.done ? "✓" : idx + 1}.</span>
                  <span className="truncate">{s.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Step 1: Name */}
        <Step
          id="name"
          title="Имя героя"
          subtitle={STEP_GUIDE.name.subtitle}
          hint={STEP_GUIDE.name.hint}
          active={activeStep === "name"}
          wizardMode={wizardMode}
          footer={renderFooter(at("name"))}
        >
          <input
            className="field w-full font-heading text-lg"
            value={draft.name}
            maxLength={80}
            placeholder="Введите имя или прозвище персонажа"
            onChange={(e) => set({ name: e.target.value })}
          />
        </Step>

        {/* Step 2: Class */}
        <Step
          id="class"
          title="Класс"
          subtitle={STEP_GUIDE.class.subtitle}
          hint={STEP_GUIDE.class.hint}
          active={activeStep === "class"}
          wizardMode={wizardMode}
          footer={renderFooter(at("class"))}
        >
          <ClassChoices
            items={opts.classes}
            weapons={opts.weapons}
            value={draft.class_id}
            onPick={(id) => {
              const next = opts.classes.find((c) => c.id === id);
              set({
                class_id: id,
                skills: [],
                fighting_style: "",
                expertise: [],
                cantrips: [],
                spells: [],
                prepared: [],
                equipment_choices: equipFor(next, [], opts),
              });
            }}
          />
        </Step>

        {/* Step 3: Origin */}
        <Step
          id="origin"
          title="Происхождение (раса)"
          subtitle={STEP_GUIDE.origin.subtitle}
          hint={STEP_GUIDE.origin.hint}
          active={activeStep === "origin"}
          wizardMode={wizardMode}
          footer={renderFooter(at("origin"))}
        >
          <OriginChoices
            items={opts.origins}
            value={draft.origin_id}
            onPick={(id) => set({ origin_id: id, ability_picks: [] })}
          />
        </Step>

        {/* Step 4: Ability Scores */}
        <Step
          id="abilities"
          title="Характеристики"
          subtitle={STEP_GUIDE.abilities.subtitle}
          hint={STEP_GUIDE.abilities.hint}
          active={activeStep === "abilities"}
          wizardMode={wizardMode}
          footer={renderFooter(at("abilities"))}
        >
          {methods.length > 1 && (
            <div className="mb-4 flex flex-wrap gap-2" role="radiogroup" aria-label="Способ распределения">
              {methods.map((m: Method) => (
                <button
                  key={m}
                  role="radio"
                  aria-checked={draft.ability_method === m}
                  className={`btn px-3 py-1.5 text-xs font-mono tracking-wider ${
                    draft.ability_method === m ? "btn-primary" : "border-line text-muted hover:text-ink"
                  }`}
                  onClick={() => setDraft((d) => withMethod(d, m))}
                >
                  {METHOD_RU[m]}
                </button>
              ))}
            </div>
          )}

          <p className="mb-4 text-xs sm:text-sm text-muted">{METHOD_HINT[draft.ability_method]}</p>

          {draft.ability_method === "point_buy" && (
            <div className="mb-4 rounded-[8px] border border-accent/40 bg-accent/10 px-3.5 py-2 font-mono text-xs text-accent">
              Потрачено очков: {pointsSpent(draft.abilities, opts.point_buy.cost)} из {opts.point_buy.budget}
            </div>
          )}

          {draft.ability_method === "roll" && !rolls ? (
            mode === "campaign" || mode === "library" ? (
              <div className="p-4 rounded-[10px] border border-line bg-raised/40">
                <ActionButton primary className="font-mono text-xs" run={roll} done="Кубики брошены">
                  БРОСИТЬ 4d6 (6 ХАРАКТЕРИСТИК)
                </ActionButton>
              </div>
            ) : null
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {ABILITIES.map((a) => (
                <div
                  key={a}
                  className="rounded-[10px] border border-line bg-raised/60 p-3 flex flex-col justify-between gap-2 transition hover:border-line/90"
                >
                  <div className="flex items-center justify-between gap-1">
                    <StatDetailTrigger type="ability" id={a} inline showIcon>
                      <span className="font-mono text-xs font-semibold text-ink hover:text-accent transition cursor-help">
                        {ABILITY_RU[a]}
                      </span>
                    </StatDetailTrigger>
                    <span className="font-mono text-[10px] text-muted uppercase">
                      {ABILITY_ABBR[a]}
                    </span>
                  </div>
                  {draft.ability_method === "point_buy" ? (
                    <PointStepper
                      value={draft.abilities[a] ?? 8}
                      cost={opts.point_buy.cost}
                      left={opts.point_buy.budget - pointsSpent(draft.abilities, opts.point_buy.cost)}
                      onChange={(v) => setAbility(a, v)}
                      label={ABILITY_RU[a]}
                    />
                  ) : (
                    <select
                      className="field font-mono text-sm py-1.5"
                      value={draft.abilities[a] ?? ""}
                      onChange={(e) => setAbility(a, e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">— выбор —</option>
                      {sortDesc(poolLeft(draft.ability_method === "roll" ? rolls! : opts.standard_array, draft.abilities, a)).map(
                        (v, i) => (
                          <option key={i} value={v}>
                            {v}
                          </option>
                        ),
                      )}
                    </select>
                  )}
                </div>
              ))}
            </div>
          )}

          {draft.ability_method === "roll" && rolls && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-xs text-muted">Выпавшие значения кубиков: {rolls.join(", ")}</p>
              {/* переброс — только у героя профиля; в кампании броски окончательные */}
              {mode === "library" && (
                <ActionButton
                  className="border-line px-3 py-1 font-mono text-xs text-muted hover:text-ink"
                  run={roll}
                  done="Кубики переброшены"
                  confirm="Перебросить все шесть характеристик? Текущие значения и расстановка пропадут."
                >
                  ПЕРЕБРОСИТЬ
                </ActionButton>
              )}
            </div>
          )}

          {/* Racial ability bonuses */}
          {origin?.ability_groups.map((g, gi) => {
            const picks = draft.ability_picks[gi] ?? [];
            const allowed = groupOptions(origin, draft.ability_picks, gi);
            return (
              <fieldset key={gi} className="mt-4 rounded-[10px] border border-line bg-raised/40 p-4">
                <legend className="font-mono text-xs font-semibold text-accent px-1">
                  {origin.name}: +{g.bonus} {g.count > 1 ? `к ${g.count} характеристикам` : "к характеристике"} на выбор
                  {g.distinct_from_prior ? ", не к той же" : ""}
                </legend>
                <div className="flex flex-wrap gap-4 mt-2">
                  {allowed.map((a) => {
                    const on = picks.includes(a);
                    return (
                      <label key={a} className="flex items-center gap-2 text-sm text-ink cursor-pointer">
                        <input
                          type="checkbox"
                          className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                          checked={on}
                          disabled={!on && picks.length >= g.count}
                          onChange={() =>
                            set({ ability_picks: setPick(origin, draft.ability_picks, gi, toggle(picks, a)) })
                          }
                        />
                        <StatDetailTrigger type="ability" id={a} inline showIcon>
                          <span className="hover:text-accent transition cursor-help">{ABILITY_RU[a]}</span>
                        </StatDetailTrigger>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            );
          })}
        </Step>

        {/* Step 5: Skills */}
        <Step
          id="skills"
          title={
            cls
              ? `Навыки (${draft.skills.length} из ${skillNeed})${cls.fighting_styles?.length ? " и боевой стиль" : ""}`
              : "Навыки"
          }
          subtitle={STEP_GUIDE.skills.subtitle}
          hint={STEP_GUIDE.skills.hint}
          active={activeStep === "skills"}
          wizardMode={wizardMode}
          footer={renderFooter(at("skills"))}
        >
          {!cls ? (
            <p className="text-sm text-muted">Сначала выберите класс: он определяет список доступных навыков.</p>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] border border-line bg-raised/40 px-3.5 py-2 text-xs">
                <div className="flex items-center gap-2 text-muted">
                  <span className="text-accent font-semibold">Мастерство:</span>
                  <span>
                    выбранные навыки получают прибавку бонуса мастерства
                    {preview.data?.derived ? ` (${signed(preview.data.derived.pb)})` : ""}.
                  </span>
                </div>
                <StatDetailTrigger type="mastery" inline showIcon>
                  <span className="font-mono text-xs font-semibold text-accent hover:underline cursor-help">
                    Подробнее о мастерстве
                  </span>
                </StatDetailTrigger>
              </div>

              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {skillFrom.map((k) => {
                  const on = draft.skills.includes(k);
                  const sk = SKILL_DETAILS[k];
                  return (
                    <StatDetailTrigger key={k} type="skill" id={k} className="w-full flex items-center gap-1.5" showIcon>
                      <label
                        className={`flex min-w-0 flex-1 items-center justify-between gap-2.5 rounded-[8px] border p-2.5 text-sm transition cursor-pointer ${
                          on
                            ? "border-accent bg-accent/10 text-ink font-medium shadow-xs"
                            : "border-line bg-raised/50 text-ink-2 hover:border-line hover:text-ink"
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <input
                            type="checkbox"
                            className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                            checked={on}
                            disabled={!on && draft.skills.length >= skillNeed}
                            onChange={() =>
                              set({ skills: toggle(draft.skills, k), expertise: draft.expertise.filter((x) => x !== k) })
                            }
                          />
                          <span className="truncate">{SKILL_RU[k] ?? k}</span>
                        </div>
                        {sk && (
                          <span className="shrink-0 rounded bg-surface/80 px-1.5 py-0.5 font-mono text-[10px] text-muted border border-line/60 uppercase">
                            {sk.abilityAbbr}
                          </span>
                        )}
                      </label>
                    </StatDetailTrigger>
                  );
                })}
              </div>

              {expertNeed > 0 && (
                <fieldset className="flex flex-col gap-2 pt-2">
                  <legend className="mb-1 text-sm font-semibold text-ink">
                    Компетентность ({draft.expertise.length} из {expertNeed})
                  </legend>
                  <p className="text-xs text-muted">
                    В этих навыках бонус мастерства удваивается. Выбирайте из навыков, которыми герой владеет.
                  </p>
                  {expertFrom.length === 0 ? (
                    <p className="text-xs text-muted">Сначала отметьте навыки выше.</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {expertFrom.map((k) => {
                        const on = draft.expertise.includes(k);
                        return (
                          <label
                            key={k}
                            className={`flex items-center gap-2 rounded-[8px] border px-2.5 py-1.5 text-sm transition cursor-pointer ${
                              on ? "border-accent bg-accent/10 text-ink" : "border-line bg-raised/50 text-ink-2"
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                              checked={on}
                              disabled={!on && draft.expertise.length >= expertNeed}
                              onChange={() => set({ expertise: toggle(draft.expertise, k) })}
                            />
                            {SKILL_RU[k] ?? k}
                          </label>
                        );
                      })}
                    </div>
                  )}
                </fieldset>
              )}

              {!!cls.fighting_styles?.length && (
                <fieldset className="flex flex-col gap-2 pt-2">
                  <legend className="mb-1 text-sm font-semibold text-ink">Боевой стиль</legend>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {cls.fighting_styles.map((fs) => {
                      const on = draft.fighting_style === fs.key;
                      return (
                        <label
                          key={fs.key}
                          className={`flex items-start gap-2.5 rounded-[8px] border p-2.5 text-sm transition cursor-pointer ${
                            on ? "border-accent bg-accent/10 text-ink" : "border-line bg-raised/50 text-ink-2"
                          }`}
                        >
                          <input
                            type="radio"
                            name="fighting_style"
                            className="accent-[var(--tf-accent)] mt-0.5 h-4 w-4"
                            checked={on}
                            onChange={() => set({ fighting_style: fs.key })}
                          />
                          <span className="flex flex-col gap-0.5">
                            <span className="font-medium">{fs.name}</span>
                            <span className="text-xs text-muted">{fs.text}</span>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              )}
            </div>
          )}
        </Step>

        {/* Заклинания — только у заклинателей */}
        {cls?.spells && sn && (
          <Step
            id="spells"
            title="Заклинания"
            subtitle={STEP_GUIDE.spells.subtitle}
            hint={STEP_GUIDE.spells.hint}
            active={activeStep === "spells"}
            wizardMode={wizardMode}
            footer={renderFooter(at("spells"))}
          >
            <SpellChoices
              cs={cls.spells}
              need={sn}
              value={{ cantrips: draft.cantrips, spells: draft.spells, prepared: draft.prepared }}
              onChange={(v) => set(v)}
            />
          </Step>
        )}

        {/* Step 6: Gear */}
        <Step
          id="gear"
          title="Стартовое снаряжение"
          subtitle={STEP_GUIDE.gear.subtitle}
          hint={STEP_GUIDE.gear.hint}
          active={activeStep === "gear"}
          wizardMode={wizardMode}
          footer={renderFooter(at("gear"))}
        >
          {!cls ? (
            <p className="text-sm text-muted">Стартовые наборы снаряжения зависят от выбранного класса.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {cls.equipment_choices.map((alts, i) => {
                const pick = draft.equipment_choices.find((x) => x.choice === i) ?? { choice: i, option: 0, items: [] };
                let slot = 0;
                return (
                  <fieldset key={i} className="flex flex-col gap-2 rounded-[10px] border border-line bg-raised/40 p-4">
                    <legend className="font-mono text-xs font-semibold text-accent uppercase tracking-wider px-1">
                      Выбор снаряжения #{i + 1}
                    </legend>
                    <div className="flex flex-col gap-2">
                      {alts.map((bundle, j) => (
                        <label key={j} className="flex items-start gap-2.5 text-sm cursor-pointer">
                          <input
                            type="radio"
                            name={`equip-${i}`}
                            className="accent-[var(--tf-accent)] mt-0.5"
                            checked={pick.option === j}
                            onChange={() =>
                              set({
                                equipment_choices: draft.equipment_choices.map((x) =>
                                    x.choice === i ? { ...x, option: j, items: weaponSlots(bundle, [], opts) } : x,
                                ),
                              })
                            }
                          />
                          <span className="text-ink">{bundle.map(partLabel).join(" + ")}</span>
                        </label>
                      ))}
                    </div>

                    <div className="flex flex-wrap gap-2 pl-6 pt-1">
                      {(alts[pick.option] ?? []).flatMap((part) =>
                        part.any
                          ? Array.from({ length: part.qty ?? 1 }, () => {
                              const k = slot++;
                              return (
                                <CustomSelect
                                  key={k}
                                  className="max-w-xs"
                                  ariaLabel="Оружие на выбор"
                                  size="sm"
                                  value={pick.items[k] ?? ""}
                                  options={weaponsOf(part.any!, opts).map(([id, name]) => ({ value: id, label: name }))}
                                  onChange={(v) =>
                                    set({
                                      equipment_choices: draft.equipment_choices.map((x) =>
                                        x.choice === i
                                          ? { ...x, items: x.items.map((val, n) => (n === k ? v : val)) }
                                          : x,
                                      ),
                                    })
                                  }
                                />
                              );
                            })
                          : [],
                      )}
                    </div>
                  </fieldset>
                );
              })}

              {cls.equipment_fixed.length > 0 && (
                <div className="font-mono text-xs text-muted">
                  Фиксированное снаряжение:{" "}
                  <span className="text-ink-2">
                    {cls.equipment_fixed
                      .map((x) => (x.name ?? x.item) + (x.qty && x.qty > 1 ? ` ×${x.qty}` : ""))
                      .join(", ")}
                  </span>
                </div>
              )}
            </div>
          )}
        </Step>

        {/* Step 7: Story / Bio */}
        <Step
          id="story"
          title="История и тайна персонажа"
          subtitle={STEP_GUIDE.story.subtitle}
          hint={STEP_GUIDE.story.hint}
          active={activeStep === "story"}
          wizardMode={wizardMode}
          footer={renderFooter(at("story"))}
        >
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-semibold text-ink">Публичное описание (видно всем за столом)</span>
            <textarea
              className="field min-h-24 text-sm"
              maxLength={2000}
              placeholder="Как выглядит герой, его манеры, что известно спутникам при первой встрече..."
              value={draft.public_bio}
              onChange={(e) => set({ public_bio: e.target.value })}
            />
          </label>

          <label className="flex flex-col gap-1.5 text-sm mt-3">
            <span className="font-semibold text-ink">Личная тайна героя (знают только вы и мастер)</span>
            <textarea
              className="field min-h-24 text-sm"
              maxLength={4000}
              placeholder="Скрытые мотивы, грехи прошлого, потаённые клятвы или артефакты..."
              value={draft.private_backstory}
              onChange={(e) => set({ private_backstory: e.target.value })}
            />
          </label>

          {preview.data && (
            <div
              className={`mt-4 rounded-[10px] border p-3.5 font-mono text-xs ${
                preview.data.errors.length
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                  : "border-patina/50 bg-patina/10 text-patina-hi font-semibold"
              }`}
            >
              {preview.data.errors.length ? (
                <div>
                  <div className="font-bold uppercase tracking-wider mb-1.5 text-amber-300">
                    Осталось заполнить для готовности:
                  </div>
                  <ul className="list-disc list-inside space-y-1 text-[11px] text-muted-hi">
                    {preview.data.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-base text-patina-hi">✓</span>
                  <span>Персонаж полностью укомплектован и готов к игре!</span>
                </div>
              )}
            </div>
          )}
        </Step>

        {/* Bottom Actions (только в режиме "Показать всё разом") */}
        {!wizardMode && (
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <ActionButton
              run={save}
              done={TITLES[mode].saved}
              primary={mode !== "campaign"}
              className="font-mono text-xs tracking-wider"
            >
              {TITLES[mode].save.toUpperCase()}
            </ActionButton>

            {mode === "campaign" && (
              <ActionButton
                run={submit}
                primary
                done="Герой отправлен мастеру на проверку"
                className="font-mono text-xs tracking-wider"
              >
                ОТПРАВИТЬ МАСТЕРУ НА ПРОВЕРКУ →
              </ActionButton>
            )}
          </div>
        )}
      </div>

      {/* Right sticky live sheet */}
      <aside id="live-sheet" className="scroll-mt-4 lg:sticky lg:top-24 lg:self-start">
        <LiveSheet preview={preview.data} loading={preview.loading} failed={preview.error} name={draft.name} />
      </aside>

      {/* Mobile Sticky Bottom Bar */}
      <a
        href="#live-sheet"
        className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-between gap-3 border-t border-line bg-surface/95 backdrop-blur-md px-4 py-2.5 font-mono text-xs text-ink no-underline lg:hidden shadow-2xl"
      >
        <span>
          {preview.data?.derived ? (
            <span className="font-semibold text-accent">
              КД {preview.data.derived.ac} · Хиты {preview.data.derived.hp_max}
            </span>
          ) : (
            "Формуляр героя"
          )}
        </span>
        <span className={preview.data && !preview.data.errors.length ? "text-patina-hi font-bold" : "text-muted"}>
          {preview.data
            ? preview.data.errors.length
              ? `Осталось: ${preview.data.errors.length}`
              : "✓ ГОТОВ"
            : "расчёт…"}
          {" ↓"}
        </span>
      </a>
    </div>
  );
}

function Step({
  id,
  title,
  subtitle,
  hint,
  active,
  wizardMode,
  children,
  footer,
}: {
  id: string;
  title: string;
  subtitle?: string;
  hint?: string;
  active: boolean;
  wizardMode: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  if (wizardMode && !active) return null;

  return (
    <section id={`step-${id}`} className="card scroll-mt-24 p-5 sm:p-6 border border-line bg-surface">
      <div className="mb-4 border-b border-line pb-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-heading text-xl font-bold text-ink">{title}</h2>
          {subtitle && (
            <span className="font-serif italic text-xs text-muted/90 tracking-wide">
              {subtitle}
            </span>
          )}
        </div>
        {hint && <p className="mt-1 text-xs text-muted/80 leading-relaxed">{hint}</p>}
      </div>
      {children}
      {wizardMode && footer}
    </section>
  );
}


function PointStepper({
  value,
  cost,
  left,
  onChange,
  label,
}: {
  value: number;
  cost: Record<string, number>;
  left: number;
  onChange: (v: number) => void;
  label: string;
}) {
  const up = value < 15 ? (cost[String(value + 1)] ?? 99) - (cost[String(value)] ?? 0) : 99;
  return (
    <div className="flex items-center justify-between rounded-[8px] border border-line bg-bg px-2 py-1">
      <button
        type="button"
        className="btn h-7 w-7 p-0 text-sm font-bold border-line text-muted hover:text-ink hover:border-accent"
        aria-label={`${label}: меньше`}
        disabled={value <= 8}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <span className="w-8 text-center font-heading text-lg font-bold text-accent tabular-nums">{value}</span>
      <button
        type="button"
        className="btn h-7 w-7 p-0 text-sm font-bold border-line text-muted hover:text-ink hover:border-accent"
        aria-label={`${label}: больше`}
        disabled={up > left}
        title={up > left && value < 15 ? `Не хватает очков: нужно ${up}` : undefined}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </div>
  );
}

/** Живой лист: через паузу после правки спрашиваем сервер, ответы на устаревшие правки отбрасываем. */
function usePreview(url: string, draft: Draft, rolls: number[] | null, extra: Record<string, unknown>) {
  const body = useMemo(() => JSON.stringify({ ...toBody(draft, rolls), ...extra }), [draft, rolls, extra]);
  const [data, setData] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    setLoading(true);
    const t = window.setTimeout(() => {
      api<Preview>(url, { method: "POST", body: JSON.parse(body) }).then(
        (p) => {
          if (my !== seq.current) return;
          setData(p);
          setError(null);
          setLoading(false);
        },
        (e: Error) => {
          if (my !== seq.current) return;
          setError(e.message);
          setLoading(false);
        },
      );
    }, 350);
    return () => window.clearTimeout(t);
  }, [url, body]);
  return { data, loading, error };
}

/** Новый выбор в группе; дальше по порядку убираем то, что теперь повторяет раннее. */
function setPick(origin: OriginOption, all: string[][], gi: number, picks: string[]): string[][] {
  const next = origin.ability_groups.map((_, i) => (i === gi ? picks : [...(all[i] ?? [])]));
  for (let i = gi + 1; i < next.length; i++) {
    const ok = groupOptions(origin, next, i);
    next[i] = next[i].filter((a) => ok.includes(a));
  }
  return next;
}

function toggle(list: string[], x: string): string[] {
  return list.includes(x) ? list.filter((y) => y !== x) : [...list, x];
}

/** Сортировка по убыванию без дедупликации — для пула бросков 4d6, где дубли допустимы. */
function sortDesc(xs: number[]): number[] {
  return [...xs].sort((a, b) => b - a);
}
