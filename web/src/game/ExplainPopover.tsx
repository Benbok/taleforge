import { useEffect, useRef, useState } from "react";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useExplain } from "./hero";
import { computePopoverPosition } from "./popoverPosition";

/** Разбор числа: из чего оно сложилось и, для хитов, последние события, которые их меняли. */
export default function ExplainPopover() {
  const { stat, anchor, close } = useExplain();
  const x = useGame((s) => (stat ? s.explained[stat] : undefined));
  const ref = useRef<HTMLDivElement>(null);
  const [, setWinSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    if (!stat) return;
    const onResize = () => setWinSize({ w: window.innerWidth, h: window.innerHeight });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const onDown = (e: MouseEvent | TouchEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("touchstart", onDown);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("touchstart", onDown);
    };
  }, [stat, close]);

  if (!stat) return null;
  const phone = typeof window !== "undefined" && window.innerWidth < 768;
  const pos = anchor && !phone ? computePopoverPosition(anchor, { cardWidth: 300 }) : null;
  const style = pos
    ? {
        left: pos.left,
        top: pos.top,
        bottom: pos.bottom,
        maxHeight: `${pos.maxHeight}px`,
      }
    : undefined;

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Почему такое число"
      className={`tf-pop fixed z-50 flex flex-col border border-line bg-surface shadow-2xl backdrop-blur-md ${
        phone ? "inset-x-0 bottom-0 max-h-[80dvh] rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]" : "w-76 rounded-xl"
      }`}
      style={style}
    >
      <div className="flex items-center justify-between gap-2 border-b border-line/60 bg-raised/80 px-4 py-3 shrink-0 rounded-t-xl">
        <p className="text-[11px] font-mono uppercase tracking-wider font-semibold text-muted">Почему такое число</p>
        <button
          type="button"
          className="flex h-7 w-7 items-center justify-center rounded-lg text-muted transition hover:bg-surface hover:text-ink shrink-0 -mr-1 -my-1 cursor-pointer"
          onClick={close}
          aria-label="Закрыть"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0 text-sm">
        {!x && (
          <p className="flex items-center gap-2 text-muted">
            <Spinner /> Считаем…
          </p>
        )}
        {x?.error && <p className="text-bad">{x.error}</p>}
        {x && !x.error && (
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold text-ink">{x.label}</span>
              <span className="text-2xl font-bold font-mono text-accent">{x.value ?? "—"}</span>
            </div>
            {x.parts && x.parts.length > 0 && (
              <ul className="flex flex-col gap-1 border-t border-line/60 pt-2 text-xs">
                {x.parts.map((p) => (
                  <li key={p.label} className="flex justify-between gap-3">
                    <span className="text-muted">{p.label}</span>
                    <span className="tabular-nums font-mono text-ink">{p.value}</span>
                  </li>
                ))}
              </ul>
            )}
            {x.note && <p className="text-xs text-muted/90 italic">{x.note}</p>}
            {x.history && (
              <div className="border-t border-line/60 pt-2">
                <p className="mb-1 text-[11px] uppercase tracking-wider font-mono text-muted">Последние изменения</p>
                {x.history.length === 0 ? (
                  <p className="text-xs text-muted">Пока ничего не случилось.</p>
                ) : (
                  <ul className="flex flex-col gap-1 text-xs">
                    {x.history.map((h, i) => (
                      <li key={i} className="text-muted/90">• {h}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
