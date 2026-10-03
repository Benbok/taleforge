import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { computePopoverPosition } from "../game/popoverPosition";
import {
  getAbilityDetail,
  getMasteryDetail,
  getSkillDetail,
  type AbilityDetail,
  type MasteryDetail,
  type SkillDetail,
} from "../game/statDetails";

const HOVER_OPEN_MS = 250;
const HOVER_CLOSE_MS = 150;
const CARD_WIDTH = 330;

type Mode = "closed" | "hover" | "pinned";

export type StatType = "ability" | "skill" | "mastery";

/** Карточка содержимого детализации: характеристика, навык или мастерство. */
export function StatDetailCardContent({
  type,
  id,
  onClose,
  isPinned,
}: {
  type: StatType;
  id?: string;
  onClose?: () => void;
  isPinned?: boolean;
}) {
  if (type === "ability") {
    const detail = id ? getAbilityDetail(id) : undefined;
    if (!detail) return null;
    return <AbilityContent detail={detail} onClose={onClose} isPinned={isPinned} />;
  }

  if (type === "skill") {
    const detail = id ? getSkillDetail(id) : undefined;
    if (!detail) return null;
    return <SkillContent detail={detail} onClose={onClose} isPinned={isPinned} />;
  }

  const detail = getMasteryDetail();
  return <MasteryContent detail={detail} onClose={onClose} isPinned={isPinned} />;
}

function AbilityContent({
  detail,
  onClose,
  isPinned,
}: {
  detail: AbilityDetail;
  onClose?: () => void;
  isPinned?: boolean;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 border-b border-line/60 bg-raised/80 px-4 py-2.5 shrink-0 rounded-t-xl">
        <div className="flex items-center gap-2">
          <span className="font-heading text-base font-bold text-ink">{detail.name}</span>
          <span className="font-mono text-xs text-muted uppercase">({detail.abbr} · {detail.enName})</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-[4px] border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase tracking-wider">
            Характеристика
          </span>
          {isPinned && onClose && (
            <button
              type="button"
              className="flex h-6 w-6 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink cursor-pointer"
              onClick={onClose}
              aria-label="Закрыть"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0 text-xs">
        <p className="font-serif italic text-muted leading-relaxed">{detail.summary}</p>
        <p className="text-ink leading-relaxed">{detail.description}</p>

        <div className="border-t border-line/50 pt-2.5 flex flex-col gap-1.5">
          <span className="font-mono text-[10px] uppercase tracking-wider font-semibold text-accent">
            Влияет на:
          </span>
          <ul className="flex flex-col gap-1 text-ink-2 leading-relaxed">
            {detail.affects.map((item, idx) => (
              <li key={idx} className="flex items-start gap-1.5">
                <span className="text-accent shrink-0 leading-tight">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

function SkillContent({
  detail,
  onClose,
  isPinned,
}: {
  detail: SkillDetail;
  onClose?: () => void;
  isPinned?: boolean;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 border-b border-line/60 bg-raised/80 px-4 py-2.5 shrink-0 rounded-t-xl">
        <div className="flex items-center gap-2">
          <span className="font-heading text-base font-bold text-ink">{detail.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-[4px] border border-patina/40 bg-patina/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-patina-hi uppercase tracking-wider">
            {detail.abilityName} ({detail.abilityAbbr})
          </span>
          {isPinned && onClose && (
            <button
              type="button"
              className="flex h-6 w-6 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink cursor-pointer"
              onClick={onClose}
              aria-label="Закрыть"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0 text-xs">
        <p className="font-serif italic text-muted leading-relaxed">{detail.summary}</p>
        <p className="text-ink leading-relaxed">{detail.description}</p>

        <div className="border-t border-line/50 pt-2.5 flex flex-col gap-1.5">
          <span className="font-mono text-[10px] uppercase tracking-wider font-semibold text-accent">
            Примеры проверок:
          </span>
          <ul className="flex flex-col gap-1 text-ink-2 leading-relaxed">
            {detail.examples.map((item, idx) => (
              <li key={idx} className="flex items-start gap-1.5">
                <span className="text-accent shrink-0 leading-tight">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-[6px] border border-accent/30 bg-accent/5 p-2 font-mono text-[11px] text-accent leading-relaxed">
          ✦ Владение навыком прибавляет бонус мастерства (+2) к проверкам характеристики.
        </div>
      </div>
    </>
  );
}

function MasteryContent({
  detail,
  onClose,
  isPinned,
}: {
  detail: MasteryDetail;
  onClose?: () => void;
  isPinned?: boolean;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-2 border-b border-line/60 bg-raised/80 px-4 py-2.5 shrink-0 rounded-t-xl">
        <div className="flex items-center gap-2">
          <span className="font-heading text-base font-bold text-ink">{detail.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-[4px] border border-accent/40 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase tracking-wider">
            Правило
          </span>
          {isPinned && onClose && (
            <button
              type="button"
              className="flex h-6 w-6 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink cursor-pointer"
              onClick={onClose}
              aria-label="Закрыть"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0 text-xs">
        <p className="font-serif italic text-muted leading-relaxed">{detail.summary}</p>
        <p className="text-ink leading-relaxed">{detail.description}</p>

        <div className="border-t border-line/50 pt-2.5 flex flex-col gap-1.5">
          <span className="font-mono text-[10px] uppercase tracking-wider font-semibold text-accent">
            Где применяется:
          </span>
          <ul className="flex flex-col gap-1.5 text-ink-2 leading-relaxed">
            {detail.howItWorks.map((item, idx) => (
              <li key={idx} className="flex items-start gap-1.5">
                <span className="text-accent shrink-0 leading-tight">✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

interface StatDetailTriggerProps {
  type: StatType;
  id?: string;
  children: ReactNode;
  className?: string;
  as?: "div" | "span" | "li" | "label";
  inline?: boolean;
  showIcon?: boolean;
}

/**
 * Обертка для любого элемента: при наведении мыши показывает детальную карточку характеристики, навыка или мастерства.
 * На сенсорных устройствах и по клику на кнопку «i» фиксирует окно.
 */
export function StatDetailTrigger({
  type,
  id,
  children,
  className = "",
  as,
  inline = false,
  showIcon = false,
}: StatDetailTriggerProps) {
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
      if (mode === "pinned" && !pop.current?.contains(t) && !wrap.current?.contains(t)) {
        close();
      }
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

  const canHover = () =>
    typeof window !== "undefined" &&
    (window.matchMedia?.("(hover: hover) and (pointer: fine)").matches ?? true);

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
    const width = Math.min(CARD_WIDTH, window.innerWidth - 24);
    const pos = computePopoverPosition(
      { top: r.top, bottom: r.bottom, left: r.left, right: r.right },
      { cardWidth: width }
    );
    style = {
      left: pos.left,
      top: pos.top,
      bottom: pos.bottom,
      maxHeight: `${pos.maxHeight}px`,
      width: `${width}px`,
    };
  }

  const Tag = as ?? (inline ? "span" : "div");

  return (
    <Tag
      ref={wrap as unknown as React.Ref<HTMLDivElement & HTMLLIElement & HTMLSpanElement & HTMLLabelElement>}
      className={`relative ${inline ? "inline-flex items-center" : "min-w-0"} ${className}`}
      onPointerEnter={hoverIn}
      onPointerLeave={hoverOut}
    >
      {children}

      {showIcon && (
        <button
          type="button"
          aria-label="Подробнее"
          title="Подробнее"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (mode === "pinned") close();
            else {
              clear();
              setMode("pinned");
            }
          }}
          className={`ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[10px] font-serif font-bold italic transition cursor-pointer ${
            open
              ? "border-accent bg-accent text-on-accent"
              : "border-line text-muted hover:border-accent hover:text-accent"
          }`}
        >
          i
        </button>
      )}

      {open &&
        createPortal(
          <div
            ref={pop}
            id={popId}
            role="dialog"
            aria-label="Детализация"
            onPointerEnter={hoverIn}
            onPointerLeave={hoverOut}
            className={`tf-pop fixed z-50 flex flex-col border border-line bg-surface shadow-2xl ${
              phone
                ? "inset-x-0 bottom-0 max-h-[80dvh] rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]"
                : "rounded-xl"
            }`}
            style={style}
          >
            <StatDetailCardContent
              type={type}
              id={id}
              onClose={close}
              isPinned={mode === "pinned"}
            />
          </div>,
          document.body
        )}
    </Tag>
  );
}

/** Отдельная аккуратная кнопка «i» со всплывающей подсказкой при наведении или клике. */
export function StatInfoButton({
  type,
  id,
  className = "",
}: {
  type: StatType;
  id?: string;
  className?: string;
}) {
  return (
    <StatDetailTrigger type={type} id={id} inline>
      <span
        tabIndex={0}
        role="button"
        aria-label="Подробнее"
        className={`inline-flex h-4 w-4 items-center justify-center rounded-full border border-line text-[10px] font-serif font-bold italic text-muted transition hover:border-accent hover:text-accent cursor-pointer ${className}`}
      >
        i
      </span>
    </StatDetailTrigger>
  );
}
