import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ABILITY_RU, SKILLS } from "../game/hero";
import { computePopoverPosition } from "../game/popoverPosition";
import type { ClassOption, OriginOption } from "../lib/builder";

const SKILL_RU = Object.fromEntries(SKILLS.map(([id, ru]) => [id, ru]));
const ARMOR_RU: Record<string, string> = { light: "лёгкие", medium: "средние", heavy: "тяжёлые", shield: "щиты" };
const WEAPON_RU: Record<string, string> = { simple: "простое", martial: "воинское" };
const SIZE_RU: Record<string, string> = { small: "маленький", medium: "средний", large: "большой" };
const HOVER_OPEN_MS = 350;
const HOVER_CLOSE_MS = 180;
const POP_WIDTH = 360;

type Mode = "closed" | "hover" | "pinned";

interface ChoiceCardProps {
  name: string;
  selected: boolean;
  onPick: () => void;
  /** Классы кнопки-карточки (рамка, высота, выделение). */
  className: string;
  children: ReactNode;
  details: ReactNode;
}

/**
 * Карточка выбора с подробностями: мышью — при наведении, на телефоне и с клавиатуры — кнопкой «i».
 * Подробности на телефоне открываются снизу листом, как разбор чисел в игре.
 */
export function ChoiceCard({ name, selected, onPick, className, children, details }: ChoiceCardProps) {
  const [mode, setMode] = useState<Mode>("closed");
  const [, setTick] = useState(0);
  const wrap = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const popId = useId();

  const clear = () => window.clearTimeout(timer.current);
  const later = (fn: () => void, ms: number) => {
    clear();
    timer.current = window.setTimeout(fn, ms);
  };
  const close = useCallback(() => {
    clear();
    setMode("closed");
  }, []);

  useEffect(() => clear, []);

  useEffect(() => {
    if (mode === "closed") return;
    const onMove = () => setTick((t) => t + 1);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (mode === "pinned" && !pop.current?.contains(t) && !wrap.current?.contains(t)) close();
    };
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [mode, close]);

  // Наведение — только там, где есть настоящая мышь; на сенсорном экране подробности открывает «i».
  const canHover = () => window.matchMedia?.("(hover: hover) and (pointer: fine)").matches ?? true;
  const hoverIn = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse" || mode === "pinned" || !canHover()) return;
    if (mode === "hover") return clear();
    later(() => setMode("hover"), HOVER_OPEN_MS);
  };
  const hoverOut = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse" || mode === "pinned") return;
    later(() => setMode("closed"), HOVER_CLOSE_MS);
  };

  const open = mode !== "closed";
  const phone = typeof window !== "undefined" && window.innerWidth < 768;
  let style: React.CSSProperties | undefined;
  if (open && !phone && wrap.current) {
    const r = wrap.current.getBoundingClientRect();
    const width = Math.min(Math.max(r.width, POP_WIDTH), window.innerWidth - 24);
    const pos = computePopoverPosition({ top: r.top, bottom: r.bottom, left: r.left }, { cardWidth: width });
    style = { left: pos.left, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxHeight, width };
  }

  return (
    <div ref={wrap} className="relative min-w-0" onPointerEnter={hoverIn} onPointerLeave={hoverOut}>
      <button type="button" role="radio" aria-checked={selected} onClick={onPick} className={className}>
        {children}
      </button>
      <button
        type="button"
        aria-label={`Подробнее: ${name}`}
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        title="Подробнее"
        onClick={() => (mode === "pinned" ? close() : (clear(), setMode("pinned")))}
        className={`absolute right-2 top-2 z-20 flex h-8 w-8 items-center justify-center rounded-full border font-serif text-sm font-bold italic shadow-md backdrop-blur transition cursor-pointer ${
          open
            ? "border-accent bg-accent text-on-accent"
            : "border-line bg-surface/85 text-muted hover:border-accent hover:text-accent"
        }`}
      >
        i
      </button>
      {open &&
        createPortal(
          <div
            ref={pop}
            id={popId}
            role="dialog"
            aria-label={`${name}: подробности`}
            onPointerEnter={hoverIn}
            onPointerLeave={hoverOut}
            className={`tf-pop fixed z-50 flex flex-col border border-line bg-surface shadow-2xl ${
              phone ? "inset-x-0 bottom-0 max-h-[80dvh] rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]" : "rounded-xl"
            }`}
            style={style}
          >
            <div className="flex items-center justify-between gap-2 border-b border-line/60 bg-raised/80 px-4 py-2.5 shrink-0 rounded-t-xl">
              <p className="font-heading text-base font-bold text-ink">{name}</p>
              {mode === "pinned" && (
                <button
                  type="button"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink cursor-pointer -mr-1"
                  onClick={close}
                  aria-label="Закрыть"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0 text-sm">{details}</div>
            {mode === "pinned" && (
              <div className="border-t border-line/60 px-4 py-3 shrink-0">
                {selected ? (
                  <p className="text-center text-sm font-semibold text-accent">✓ Выбрано</p>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary w-full"
                    onClick={() => {
                      onPick();
                      close();
                    }}
                  >
                    Выбрать
                  </button>
                )}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 border-t border-line/60 pt-2.5">
      <p className="text-[11px] font-mono uppercase tracking-wider font-semibold text-muted">{title}</p>
      {children}
    </div>
  );
}

function Facts({ rows }: { rows: [string, string | null | undefined][] }) {
  const shown = rows.filter(([, v]) => v);
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Intro({ epithet, summary, description }: { epithet?: string; summary?: string; description?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      {epithet && <p className="font-serif italic text-xs text-muted">{epithet}</p>}
      {summary && <p className="text-ink leading-relaxed">{summary}</p>}
      {description && description !== summary && <p className="text-xs text-muted leading-relaxed">{description}</p>}
    </div>
  );
}

function Bullets({ items }: { items: { title?: string; text: string }[] }) {
  return (
    <ul className="flex flex-col gap-1.5 text-xs leading-relaxed">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2">
          <span className="text-accent">•</span>
          <span className="text-ink/90">
            {x.title && <span className="font-semibold text-ink">{x.title}. </span>}
            {x.text}
          </span>
        </li>
      ))}
    </ul>
  );
}

const joinRu = (xs: string[]) => xs.filter(Boolean).join(", ");

export function ClassDetails({ c, weapons }: { c: ClassOption; weapons: Record<string, { name: string }> }) {
  const p = c.proficiencies ?? {};
  const choose = c.skills_choose ?? {};
  const skillsFrom =
    choose.from?.length && choose.from.length < SKILLS.length ? joinRu(choose.from.map((s) => SKILL_RU[s] ?? s)) : "любые";
  return (
    <>
      <Intro epithet={c.epithet} summary={c.summary} description={c.description} />
      {!!c.highlights?.length && (
        <Section title="Особенности">
          <Bullets items={c.highlights.map((text) => ({ text }))} />
        </Section>
      )}
      <Section title="Основа">
        <Facts
          rows={[
            ["Кость хитов", c.hit_die ? `d${c.hit_die}` : null],
            ["Спасброски", joinRu(c.saving_throws.map((a) => ABILITY_RU[a] ?? a))],
            ["Заклинания", c.spellcasting_ability ? `на ${ABILITY_RU[c.spellcasting_ability] ?? c.spellcasting_ability}` : null],
            ["Доспехи", joinRu((p.armor ?? []).map((a) => ARMOR_RU[a] ?? a))],
            ["Оружие", joinRu((p.weapons ?? []).map((w) => WEAPON_RU[w] ?? weapons[w]?.name ?? w))],
            ["Навыки", choose.count ? `${choose.count} на выбор: ${skillsFrom}` : null],
          ]}
        />
      </Section>
      {!!c.subclasses?.length && (
        <Section title="Пути развития">
          <Bullets items={c.subclasses.map((s) => ({ title: s.name, text: s.description }))} />
        </Section>
      )}
    </>
  );
}

export function OriginDetails({ o, stats }: { o: OriginOption; stats: string }) {
  const p = o.proficiencies ?? {};
  // SRD даёт черты по-английски, поэтому у него свои русские highlights; пакет мира пишет черты сразу по-русски.
  const feats = o.highlights?.length
    ? o.highlights.map((text) => ({ text }))
    : (o.traits ?? []).map((t) => ({ title: t.name, text: t.description }));
  const skills = joinRu((p.skills ?? []).map((s) => SKILL_RU[s] ?? s));
  return (
    <>
      <Intro epithet={o.epithet} summary={o.summary} description={o.description} />
      {!!feats.length && (
        <Section title="Особенности">
          <Bullets items={feats} />
        </Section>
      )}
      <Section title="Основа">
        <Facts
          rows={[
            ["Прибавки", stats],
            ["Скорость", o.speed ? `${o.speed} фт.` : null],
            ["Размер", o.size ? (SIZE_RU[o.size] ?? o.size) : null],
            ["Тёмное зрение", o.darkvision ? `${o.darkvision} фт.` : null],
            ["Навыки", skills || (p.skills_choose?.count ? `${p.skills_choose.count} на выбор` : null)],
          ]}
        />
      </Section>
    </>
  );
}
