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
  library: { save: "Сохранить героя", saved: "Герой сохранён" },
};

/** Конструктор героя: слева выбор по шагам, справа живой лист, который считает сервер по правилам кампании. */
export default function Builder({
  mode,
  campaignId,
  opts,
  hero,
  onSaved,
  onSubmitted,
  asSeat,
}: {
  mode: BuilderMode;
  campaignId?: string;
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
  const preview = usePreview(urls.preview, draft, rolls);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setAbility = (a: string, v: number | null) => setDraft((d) => ({ ...d, abilities: { ...d.abilities, [a]: v } }));

  async function save(): Promise<SavedHero> {
    const obj = await api<SavedHero>(urls.save, { method: saved ? "PUT" : "POST", body: toBody(draft, rolls) });
    setSaved(obj);
    onSaved(obj);
    return obj;
  }

  async function roll() {
    const obj = saved ?? (await save());
    const r = await api<{ rolls: number[] }>(builderUrls(mode, campaignId, obj.id, asSeat).roll!, { method: "POST" });
    setRolls(r.rolls);
    setDraft((d) => ({ ...d, abilities: Object.fromEntries(ABILITIES.map((a) => [a, null])) }));
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

  const st = steps(draft, opts);
  const skillNeed = cls?.skills_choose?.count ?? 0;
  const skillFrom = cls?.skills_choose?.from?.length ? cls.skills_choose.from : SKILLS.map(([id]) => id);

  return (
    <div className="grid gap-6 pb-12 lg:grid-cols-[minmax(0,1fr)_22rem] lg:pb-0">
      <div className="flex min-w-0 flex-col gap-5">
        <nav aria-label="Шаги" className="flex flex-wrap gap-2">
          {st.map((s) => (
            <a
              key={s.id}
              href={`#step-${s.id}`}
              className={`rounded-full border px-2.5 py-0.5 text-xs no-underline ${s.done ? "border-ok text-ok" : "border-line text-muted"}`}
            >
              {s.done ? "✓ " : ""}
              {s.label}
            </a>
          ))}
        </nav>

        <Step id="name" title="Имя">
          <input
            className="field w-full"
            value={draft.name}
            maxLength={80}
            placeholder="Как зовут героя"
            onChange={(e) => set({ name: e.target.value })}
          />
        </Step>

        <Step id="class" title="Класс">
          <Choices
            items={opts.classes}
            value={draft.class_id}
            meta={(c) => [c.hit_die ? `кость хитов d${c.hit_die}` : null, c.saving_throws.map((a) => ABILITY_RU[a]).join(", ")]}
            onPick={(id) => {
              const next = opts.classes.find((c) => c.id === id);
              set({ class_id: id, skills: [], equipment_choices: equipFor(next, [], opts) });
            }}
          />
        </Step>

        <Step id="origin" title="Происхождение">
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

        <Step id="abilities" title="Характеристики">
          {methods.length > 1 && (
            <div className="mb-3 flex flex-wrap gap-2" role="radiogroup" aria-label="Способ">
              {methods.map((m: Method) => (
                <button
                  key={m}
                  role="radio"
                  aria-checked={draft.ability_method === m}
                  className={`btn px-3 py-1 ${draft.ability_method === m ? "btn-primary" : ""}`}
                  onClick={() => setDraft((d) => withMethod(d, m))}
                >
                  {METHOD_RU[m]}
                </button>
              ))}
            </div>
          )}
          <p className="mb-3 text-sm text-muted">{METHOD_HINT[draft.ability_method]}</p>
          {draft.ability_method === "point_buy" && (
            <p className="mb-2 text-sm">
              Потрачено {pointsSpent(draft.abilities, opts.point_buy.cost)} из {opts.point_buy.budget}
            </p>
          )}
          {draft.ability_method === "roll" && !rolls ? (
            mode === "campaign" || mode === "library" ? (
              <ActionButton primary run={roll} done="Кубики брошены">
                Бросить 4d6
              </ActionButton>
            ) : null
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {ABILITIES.map((a) => (
                <label key={a} className="flex flex-col gap-1 text-sm">
                  {ABILITY_RU[a]}
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
                      className="field"
                      value={draft.abilities[a] ?? ""}
                      onChange={(e) => setAbility(a, e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">—</option>
                      {uniq(poolLeft(draft.ability_method === "roll" ? rolls! : opts.standard_array, draft.abilities, a)).map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              ))}
            </div>
          )}
          {draft.ability_method === "roll" && rolls && <p className="mt-2 text-sm text-muted">Выпало: {rolls.join(", ")}</p>}
          {origin?.ability_groups.map((g, gi) => {
            const picks = draft.ability_picks[gi] ?? [];
            const allowed = groupOptions(origin, draft.ability_picks, gi);
            return (
              <fieldset key={gi} className="mt-4">
                <legend className="mb-1 text-sm">
                  {origin.name}: +{g.bonus} {g.count > 1 ? `к ${g.count} характеристикам` : "к характеристике"} на выбор
                  {g.distinct_from_prior ? ", не к той же" : ""}
                </legend>
                <div className="flex flex-wrap gap-3">
                  {allowed.map((a) => {
                    const on = picks.includes(a);
                    return (
                      <label key={a} className="flex items-center gap-1.5 text-sm">
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={!on && picks.length >= g.count}
                          onChange={() => set({ ability_picks: setPick(origin, draft.ability_picks, gi, toggle(picks, a)) })}
                        />
                        {ABILITY_RU[a]}
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            );
          })}
        </Step>

        <Step id="skills" title={cls ? `Навыки: ${draft.skills.length} из ${skillNeed}` : "Навыки"}>
          {!cls ? (
            <p className="text-sm text-muted">Сначала выберите класс: он решает, из каких навыков выбирать.</p>
          ) : (
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {skillFrom.map((k) => {
                const on = draft.skills.includes(k);
                return (
                  <label key={k} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!on && draft.skills.length >= skillNeed}
                      onChange={() => set({ skills: toggle(draft.skills, k) })}
                    />
                    {SKILL_RU[k] ?? k}
                  </label>
                );
              })}
            </div>
          )}
        </Step>

        <Step id="gear" title="Снаряжение">
          {!cls ? (
            <p className="text-sm text-muted">Стартовые наборы зависят от класса.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {cls.equipment_choices.map((alts, i) => {
                const pick = draft.equipment_choices.find((x) => x.choice === i) ?? { choice: i, option: 0, items: [] };
                let slot = 0;
                return (
                  <fieldset key={i} className="flex flex-col gap-1.5">
                    <legend className="mb-1 text-sm text-muted">Набор {i + 1}</legend>
                    {alts.map((bundle, j) => (
                      <label key={j} className="flex items-start gap-2 text-sm">
                        <input
                          type="radio"
                          name={`equip-${i}`}
                          checked={pick.option === j}
                          onChange={() =>
                            set({
                              equipment_choices: draft.equipment_choices.map((x) =>
                                x.choice === i ? { ...x, option: j, items: weaponSlots(bundle, [], opts) } : x,
                              ),
                            })
                          }
                        />
                        <span>{bundle.map(partLabel).join(" + ")}</span>
                      </label>
                    ))}
                    <div className="flex flex-wrap gap-2 pl-6">
                      {(alts[pick.option] ?? []).flatMap((part) =>
                        part.any
                          ? Array.from({ length: part.qty ?? 1 }, () => {
                              const k = slot++;
                              return (
                                <select
                                  key={k}
                                  className="field"
                                  aria-label="Оружие на выбор"
                                  value={pick.items[k] ?? ""}
                                  onChange={(e) =>
                                    set({
                                      equipment_choices: draft.equipment_choices.map((x) =>
                                        x.choice === i ? { ...x, items: x.items.map((v, n) => (n === k ? e.target.value : v)) } : x,
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
                <p className="text-sm text-muted">
                  Также:{" "}
                  {cls.equipment_fixed.map((x) => (x.name ?? x.item) + (x.qty && x.qty > 1 ? ` ×${x.qty}` : "")).join(", ")}
                </p>
              )}
            </div>
          )}
        </Step>

        <Step id="story" title="История">
          <label className="mb-3 flex flex-col gap-1 text-sm">
            Кто он для других: это увидят все за столом
            <textarea
              className="field min-h-20"
              maxLength={2000}
              value={draft.public_bio}
              onChange={(e) => set({ public_bio: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Тайна героя: её знают только мастер и вы
            <textarea
              className="field min-h-20"
              maxLength={4000}
              value={draft.private_backstory}
              onChange={(e) => set({ private_backstory: e.target.value })}
            />
          </label>
        </Step>

        <div className="flex flex-wrap items-start gap-3">
          <ActionButton run={save} done={TITLES[mode].saved} primary={mode !== "campaign"}>
            {TITLES[mode].save}
          </ActionButton>
          {mode === "campaign" && (
            <ActionButton run={submit} primary done="Герой отправлен мастеру">
              Отправить мастеру
            </ActionButton>
          )}
        </div>
      </div>

      <aside id="live-sheet" className="scroll-mt-4 lg:sticky lg:top-4 lg:self-start">
        <LiveSheet preview={preview.data} loading={preview.loading} failed={preview.error} name={draft.name} />
      </aside>
      {/* на телефоне лист — внизу страницы, а главные числа всегда перед глазами */}
      <a
        href="#live-sheet"
        className="fixed inset-x-0 bottom-0 z-20 flex items-center justify-between gap-3 border-t border-line bg-surface px-4 py-2 text-sm text-ink no-underline lg:hidden"
      >
        <span>
          {preview.data?.derived ? `КД ${preview.data.derived.ac} · Хиты ${preview.data.derived.hp_max}` : "Лист героя"}
        </span>
        <span className={preview.data && !preview.data.errors.length ? "text-ok" : "text-muted"}>
          {preview.data ? (preview.data.errors.length ? `осталось: ${preview.data.errors.length}` : "готов") : "…"} ↓
        </span>
      </a>
    </div>
  );
}

function Step({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={`step-${id}`} className="card scroll-mt-4 p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
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
    <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">
      {items.map((x) => {
        const on = x.id === value;
        return (
          <button
            key={x.id}
            role="radio"
            aria-checked={on}
            className={`rounded-md border p-3 text-left transition-colors ${on ? "border-accent bg-raised" : "border-line hover:border-muted"}`}
            onClick={() => onPick(x.id)}
          >
            <span className="block font-semibold">
              {on ? "✓ " : ""}
              {x.name}
            </span>
            <span className="block text-xs text-muted">{meta(x).filter(Boolean).join(" · ")}</span>
            {x.description && <span className="mt-1 line-clamp-3 block text-sm text-muted">{x.description}</span>}
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
    <span className="flex items-center gap-2">
      <button className="btn px-2 py-0.5" aria-label={`${label}: меньше`} disabled={value <= 8} onClick={() => onChange(value - 1)}>
        −
      </button>
      <span className="w-6 text-center tabular-nums">{value}</span>
      <button
        className="btn px-2 py-0.5"
        aria-label={`${label}: больше`}
        disabled={up > left}
        title={up > left && value < 15 ? `Не хватает очков: нужно ${up}` : undefined}
        onClick={() => onChange(value + 1)}
      >
        +
      </button>
    </span>
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
