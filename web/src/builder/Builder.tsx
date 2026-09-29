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
import { ABILITIES, ABILITY_RU, SKILLS } from "../game/hero";
import LiveSheet from "./LiveSheet";

const SKILL_RU = Object.fromEntries(SKILLS.map(([id, ru]) => [id, ru]));

const TITLES: Record<BuilderMode, { save: string; saved: string }> = {
  campaign: { save: "Сохранить черновик", saved: "Черновик сохранён" },
  premade: { save: "Сохранить заготовку", saved: "Заготовка сохранена" },
  library: { save: "Сохранить в библиотеку", saved: "Герой сохранён в библиотеке" },
};

/** Конструктор героя: слева выбор по шагам, справа живой лист, который считает сервер по правилам кампании. */
export default function Builder({
  mode,
  campaignId,
  opts,
  hero,
  onSaved,
  onSubmitted,
}: {
  mode: BuilderMode;
  campaignId?: string;
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
  const urls = builderUrls(mode, campaignId, saved?.id);
  const cls = opts.classes.find((c) => c.id === draft.class_id);
  const origin = opts.origins.find((o) => o.id === draft.origin_id);
  const preview = usePreview(urls.preview, draft, rolls);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setAbility = (a: string, v: number | null) =>
    setDraft((d) => ({ ...d, abilities: { ...d.abilities, [a]: v } }));

  async function save(): Promise<SavedHero> {
    const obj = await api<SavedHero>(urls.save, { method: saved ? "PUT" : "POST", body: toBody(draft, rolls) });
    setSaved(obj);
    onSaved(obj);
    return obj;
  }

  async function roll() {
    const obj = saved ?? (await save());
    const r = await api<{ rolls: number[] }>(builderUrls(mode, campaignId, obj.id).roll!, { method: "POST" });
    setRolls(r.rolls);
    setDraft((d) => ({ ...d, abilities: Object.fromEntries(ABILITIES.map((a) => [a, null])) }));
  }

  async function submit() {
    const obj = await save();
    if (obj.errors?.length) throw new Error(`Не хватает: ${obj.errors.join("; ")}`);
    const r = await api<{ status: string; errors: string[] }>(
      `/api/campaigns/${campaignId}/characters/${obj.id}/submit`,
      { method: "POST" },
    );
    if (r.errors.length) throw new Error(r.errors.join("; "));
    onSubmitted?.(r.status);
  }

  const st = steps(draft, opts);
  const skillNeed = cls?.skills_choose?.count ?? 0;
  const skillFrom = cls?.skills_choose?.from?.length ? cls.skills_choose.from : SKILLS.map(([id]) => id);

  return (
    <div className="grid gap-6 pb-16 lg:grid-cols-[minmax(0,1fr)_23rem] lg:pb-0">
      <div className="flex min-w-0 flex-col gap-6">
        {/* Step Navigation Pills */}
        <nav
          aria-label="Шаги создания героя"
          className="flex flex-wrap gap-2 rounded-[12px] border border-line bg-surface p-3"
        >
          {st.map((s) => (
            <a
              key={s.id}
              href={`#step-${s.id}`}
              className={`rounded-full border px-3 py-1 font-mono text-[11px] no-underline transition ${
                s.done
                  ? "border-patina/50 bg-patina/10 text-patina-hi font-semibold"
                  : "border-line bg-raised text-muted hover:border-accent hover:text-ink"
              }`}
            >
              {s.done ? "✓ " : ""}
              {s.label}
            </a>
          ))}
        </nav>

        {/* Step 1: Name */}
        <Step id="name" title="Имя героя">
          <input
            className="field w-full font-heading text-lg"
            value={draft.name}
            maxLength={80}
            placeholder="Введите имя или прозвище персонажа"
            onChange={(e) => set({ name: e.target.value })}
          />
        </Step>

        {/* Step 2: Class */}
        <Step id="class" title="Класс">
          <Choices
            items={opts.classes}
            value={draft.class_id}
            meta={(c) => [
              c.hit_die ? `кость хитов d${c.hit_die}` : null,
              c.saving_throws.map((a) => ABILITY_RU[a]).join(", "),
            ]}
            onPick={(id) => {
              const next = opts.classes.find((c) => c.id === id);
              set({ class_id: id, skills: [], equipment_choices: equipFor(next, [], opts) });
            }}
          />
        </Step>

        {/* Step 3: Origin */}
        <Step id="origin" title="Происхождение (раса)">
          <Choices
            items={opts.origins}
            value={draft.origin_id}
            meta={(o) => [
              [
                ...Object.entries(o.ability_bonuses).map(([a, b]) => `${ABILITY_RU[a] ?? a} +${b}`),
                ...o.ability_groups.map((g) => `+${g.bonus} на выбор${g.count > 1 ? ` ×${g.count}` : ""}`),
              ].join(", ") || null,
              o.speed ? `скорость ${o.speed} фт.` : null,
            ]}
            onPick={(id) => set({ origin_id: id, ability_picks: [] })}
          />
        </Step>

        {/* Step 4: Ability Scores */}
        <Step id="abilities" title="Характеристики">
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
                  className="rounded-[10px] border border-line bg-raised/60 p-3 flex flex-col justify-between gap-2"
                >
                  <span className="font-mono text-xs font-semibold text-ink">{ABILITY_RU[a]}</span>
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
                      {uniq(poolLeft(draft.ability_method === "roll" ? rolls! : opts.standard_array, draft.abilities, a)).map(
                        (v) => (
                          <option key={v} value={v}>
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
            <p className="mt-3 font-mono text-xs text-muted">Выпавшие значения кубиков: {rolls.join(", ")}</p>
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
                        <span>{ABILITY_RU[a]}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            );
          })}
        </Step>

        {/* Step 5: Skills */}
        <Step id="skills" title={cls ? `Навыки (${draft.skills.length} из ${skillNeed})` : "Навыки"}>
          {!cls ? (
            <p className="text-sm text-muted">Сначала выберите класс: он определяет список доступных навыков.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {skillFrom.map((k) => {
                const on = draft.skills.includes(k);
                return (
                  <label
                    key={k}
                    className={`flex items-center gap-2.5 rounded-[8px] border p-2.5 text-sm transition cursor-pointer ${
                      on
                        ? "border-accent bg-accent/10 text-ink font-medium"
                        : "border-line bg-raised/50 text-ink-2 hover:border-line"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="accent-[var(--tf-accent)] h-4 w-4 rounded"
                      checked={on}
                      disabled={!on && draft.skills.length >= skillNeed}
                      onChange={() => set({ skills: toggle(draft.skills, k) })}
                    />
                    <span>{SKILL_RU[k] ?? k}</span>
                  </label>
                );
              })}
            </div>
          )}
        </Step>

        {/* Step 6: Gear */}
        <Step id="gear" title="Стартовое снаряжение">
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
                                <select
                                  key={k}
                                  className="field font-mono text-xs max-w-xs"
                                  aria-label="Оружие на выбор"
                                  value={pick.items[k] ?? ""}
                                  onChange={(e) =>
                                    set({
                                      equipment_choices: draft.equipment_choices.map((x) =>
                                        x.choice === i
                                          ? { ...x, items: x.items.map((v, n) => (n === k ? e.target.value : v)) }
                                          : x,
                                      ),
                                    })
                                  }
                                >
                                  {weaponsOf(part.any!, opts).map(([id, name]) => (
                                    <option key={id} value={id}>
                                      {name}
                                    </option>
                                  ))}
                                </select>
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
        <Step id="story" title="История и тайна персонажа">
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
        </Step>

        {/* Bottom Actions */}
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

function Step({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={`step-${id}`} className="card scroll-mt-24 p-5 sm:p-6 border border-line bg-surface">
      <h2 className="mb-4 font-heading text-xl font-bold text-ink border-b border-line pb-2.5">{title}</h2>
      {children}
    </section>
  );
}

function Choices<T extends { id: string; name: string; description: string }>({
  items,
  value,
  meta,
  onPick,
}: {
  items: T[];
  value: string;
  meta: (x: T) => (string | null)[];
  onPick: (id: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
      {items.map((x) => {
        const on = x.id === value;
        return (
          <button
            key={x.id}
            type="button"
            role="radio"
            aria-checked={on}
            className={`group rounded-[12px] border p-4 text-left transition ${
              on
                ? "border-accent bg-accent/10 shadow-[0_0_12px_rgba(201,138,75,0.15)] ring-1 ring-accent/30"
                : "border-line bg-raised/40 hover:border-accent/60 hover:bg-raised/70"
            }`}
            onClick={() => onPick(x.id)}
          >
            <div className="flex items-center justify-between gap-2">
              <span className={`font-heading text-base font-bold transition ${on ? "text-accent" : "text-ink"}`}>
                {on ? "✓ " : ""}
                {x.name}
              </span>
            </div>
            <span className="block font-mono text-[11px] text-accent mt-1">
              {meta(x).filter(Boolean).join(" · ")}
            </span>
            {x.description && (
              <span className="mt-2 line-clamp-3 block text-xs text-muted leading-relaxed">
                {x.description}
              </span>
            )}
          </button>
        );
      })}
    </div>
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
function usePreview(url: string, draft: Draft, rolls: number[] | null) {
  const body = useMemo(() => JSON.stringify(toBody(draft, rolls)), [draft, rolls]);
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

function uniq(xs: number[]): number[] {
  return [...new Set(xs)].sort((a, b) => b - a);
}
