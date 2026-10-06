import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { SpellCard, Spellbook as Book } from "../lib/spells";
import { spellMeta } from "../lib/spells";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { candidates, castLine, multi, rangeWarnings, steps, targetProblem, ZONE_RU, type Step } from "./castPlan";
import { cast } from "./quick";

const STEP_TITLE: Record<Step, string> = {
  target: "Цель",
  slot: "Ячейка",
  confirm: "Проверка",
};

const GROUP_RU = { foe: "враг", other: "существо", ally: "союзник" } as const;

/** Пошаговое окно сотворения: цель → ячейка или ритуал → как именно → проверка и «Сотворить». */
export default function CastWizard({
  s,
  b,
  slots,
  canRitual,
  onClose,
  onCast,
}: {
  s: SpellCard;
  b: Book;
  /** Ячейки, которыми можно сотворить: [круг, подпись]. */
  slots: [number, string][];
  canRitual: boolean;
  onClose: () => void;
  onCast: () => void;
}) {
  const scene = useGame((st) => st.scene);
  const heroes = useGame((st) => st.heroes);
  const myId = useGame((st) => st.sheet?.id ?? "");

  const list = useMemo(() => {
    const creatures = (scene?.entities ?? [])
      .filter((e) => e.kind === "creature" && e.condition !== "мёртв")
      .map((e) => ({ id: e.id, name: e.name, zone: e.zone, hostile: e.attitude === "hostile" }));
    const allies = Object.values(heroes)
      .filter((x) => !x.dead)
      .map((x) => ({ id: x.id, name: x.id === myId ? `${x.name} (вы)` : x.name }));
    return candidates(s, creatures, allies);
  }, [scene, heroes, myId, s]);

  const leveled = s.level > 0;
  const plan = steps(leveled ? slots.length : 0, leveled && canRitual);
  const self = s.targets === "self";
  const [at, setAt] = useState(0);
  const [chosen, setChosen] = useState<string[]>([]);
  // ячеек нет, но можно ритуалом — выбор сделан за игрока
  const [ritual, setRitual] = useState(leveled && slots.length === 0 && canRitual);
  const [slot, setSlot] = useState<number | null>(slots[0]?.[0] ?? null);
  const [manner, setManner] = useState("");
  // цель словами игрока — главное поле шага: так можно назвать и то, чего нет в сцене («факел на стене»), это
  // заведёт мастер. У заклинаний на себя здесь описание: кем становитесь, как выглядит
  const [described, setDescribed] = useState("");
  const step = plan[at];
  const area = multi(s);
  const picked = list.filter((c) => chosen.includes(c.id));
  const words = described.trim();
  const names = [...picked.map((c) => c.name.replace(" (вы)", "")), ...(!self && words ? [words] : [])];
  const how = [self ? words : "", manner.trim()].filter(Boolean).join(". ");
  const slotLvl = leveled && !ritual ? slot : null;
  const text = castLine(s.name, names, slotLvl && slotLvl > s.level ? slotLvl : null, ritual, how, area);
  const warnings = rangeWarnings(s, picked);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation(); // закрываем только окно сотворения, книга остаётся открытой
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  function toggle(id: string) {
    if (area) setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
    else setChosen(chosen.includes(id) ? [] : [id]);
  }

  function next() {
    if (step === "target") {
      const problem = targetProblem(s, chosen, described);
      if (problem) return toast.error(problem);
    }
    if (step === "slot" && !ritual && slot == null) return toast.error("Выберите ячейку или ритуал.");
    setAt(Math.min(at + 1, plan.length - 1));
  }

  function go() {
    const err = cast({
      spellId: s.id,
      text,
      targets: chosen,
      other: !self && words ? words : null,
      area,
      slot: slotLvl && slotLvl > s.level ? slotLvl : null,
      ritual,
      manner: how,
    });
    if (err) return toast.error(err);
    toast.ok(`«${s.name}»: заявлено мастеру`);
    onClose();
    onCast();
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 md:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label={`Сотворить «${s.name}»`} className="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-xl border border-accent/50 bg-surface md:rounded-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line p-4">
          <div className="min-w-0">
            <h2 className="truncate font-heading text-lg font-bold text-ink">{s.name}</h2>
            <p className="text-xs text-muted">{spellMeta(s)}</p>
          </div>
          <button className="text-2xl leading-none text-muted hover:text-ink" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <ol className="flex gap-1 border-b border-line px-4 py-2 text-xs" aria-label="Шаги">
          {plan.map((p, i) => (
            <li key={p} className={i === at ? "font-semibold text-accent" : i < at ? "text-ink" : "text-muted"}>
              {i > 0 && <span className="mx-1 text-muted">›</span>}
              {i < at ? "✓ " : ""}
              {STEP_TITLE[p]}
            </li>
          ))}
        </ol>

        <div className="flex flex-col gap-3 overflow-y-auto p-4 text-sm">
          {step === "target" && (
            <>
              <label className="flex flex-col gap-1.5">
                <span className="text-muted">
                  {self
                    ? "Что именно происходит? Например, для «Мимикрии» — кем вы становитесь. Можно оставить пустым."
                    : area
                      ? "Кого или что накроет область, где она? Опишите своими словами."
                      : "Кто или что цель? Если заклинание создаёт образ или предмет — что это и где. Опишите своими словами."}
                </span>
                <textarea
                  className="field min-h-16 text-sm"
                  maxLength={300}
                  value={described}
                  onChange={(e) => setDescribed(e.target.value)}
                  placeholder={
                    self
                      ? "Например: сутулый портовый грузчик в просмолённой куртке"
                      : "Например: факел на стене; или иллюзорный ящик у двери"
                  }
                  autoFocus
                />
              </label>
              {!self && list.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs text-muted">
                    {area
                      ? s.range.startsWith("на себя")
                        ? "Или отметьте из сцены всех, кто внутри:"
                        : "Или отметьте из сцены всех, кто внутри. Первый отмеченный — центр области:"
                      : "Или выберите из сцены:"}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {list.map((c) => {
                      const on = chosen.includes(c.id);
                      return (
                        <button
                          key={c.id}
                          role={area ? "checkbox" : "radio"}
                          aria-checked={on}
                          onClick={() => toggle(c.id)}
                          title={`${GROUP_RU[c.group]}${c.zone ? `, ${ZONE_RU[c.zone] ?? c.zone}` : ""}`}
                          className={`rounded-full border px-2.5 py-1 text-xs ${
                            on ? "border-accent bg-accent/10 text-accent" : "border-line hover:border-accent/60"
                          }`}
                        >
                          {on ? "✓ " : ""}
                          {c.name}
                          {c.zone ? <span className="text-muted"> · {ZONE_RU[c.zone] ?? c.zone}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {!self && words && (
                <p className="text-xs text-muted">Что названо словами и чего нет в сцене, мастер сначала заведёт, потом проведёт заклинание.</p>
              )}
              <label className="flex flex-col gap-1.5">
                <span className="text-muted">
                  Как именно? Необязательно.
                  {s.area && s.range.startsWith("на себя") ? " Для конуса и линии укажите, в какую сторону." : ""}
                </span>
                <input
                  className="field text-sm"
                  maxLength={200}
                  value={manner}
                  onChange={(e) => setManner(e.target.value)}
                  placeholder="Например: из-за ящиков, целясь в руку"
                />
              </label>
            </>
          )}

          {step === "slot" && (
            <>
              <p className="text-muted">Какой ячейкой? Ячейка выше круга усиливает заклинание, если у него есть усиление.</p>
              <div className="flex flex-col gap-1.5" role="radiogroup">
                {slots.map(([lvl, label]) => (
                  <label key={lvl} className="flex items-center gap-2 rounded-md border border-line px-3 py-2">
                    <input type="radio" checked={!ritual && slot === lvl} onChange={() => (setRitual(false), setSlot(lvl))} />
                    {label}
                  </label>
                ))}
                {canRitual && (
                  <label className="flex items-center gap-2 rounded-md border border-line px-3 py-2" title="Без ячейки, на 10 минут дольше">
                    <input type="radio" checked={ritual} onChange={() => setRitual(true)} />
                    Ритуалом: без ячейки, на 10 минут дольше
                  </label>
                )}
              </div>
            </>
          )}

          {step === "confirm" && (
            <>
              <p className="rounded-md bg-raised px-3 py-2 font-narration">{text}</p>
              {s.concentration && b.concentration && (
                <p className="text-warn">Концентрация на «{b.concentration.name}» прервётся.</p>
              )}
              {warnings.map((w) => (
                <p key={w} className="text-warn">
                  {w}
                </p>
              ))}
              <p className="text-xs text-muted">Бросок, урон и спасброски посчитает сервер по базе заклинаний.</p>
            </>
          )}
        </div>

        <footer className="flex justify-between gap-2 border-t border-line p-3">
          <button className="btn px-3 py-1.5 text-xs" onClick={() => (at === 0 ? onClose() : setAt(at - 1))}>
            {at === 0 ? "Отмена" : "Назад"}
          </button>
          {step === "confirm" ? (
            <button className="btn btn-primary px-4 py-1.5 text-xs" onClick={go}>
              Сотворить
            </button>
          ) : (
            <button className="btn btn-primary px-4 py-1.5 text-xs" onClick={next}>
              Далее
            </button>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
