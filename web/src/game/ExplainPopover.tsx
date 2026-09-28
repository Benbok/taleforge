import { useEffect, useRef } from "react";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useExplain } from "./hero";

/** Разбор числа: из чего оно сложилось и, для хитов, последние события, которые их меняли. */
export default function ExplainPopover() {
  const { stat, anchor, close } = useExplain();
  const x = useGame((s) => (stat ? s.explained[stat] : undefined));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!stat) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [stat, close]);

  if (!stat) return null;
  const phone = window.innerWidth < 768;
  const style =
    anchor && !phone
      ? {
          left: Math.min(Math.max(8, anchor.left), window.innerWidth - 304),
          top: anchor.bottom + 8 + 260 > window.innerHeight ? Math.max(8, anchor.top - 268) : anchor.bottom + 8,
        }
      : undefined;
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Почему такое число"
      className={`tf-pop fixed z-50 max-h-[60dvh] overflow-y-auto border border-line bg-raised p-4 shadow-xl ${
        style ? "w-72 rounded-lg" : "inset-x-0 bottom-0 rounded-t-xl"
      }`}
      style={style}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="text-xs uppercase tracking-wide text-muted">Почему такое число</p>
        <button className="text-muted hover:text-ink" onClick={close} aria-label="Закрыть">
          ×
        </button>
      </div>
      {!x && (
        <p className="flex items-center gap-2 text-muted">
          <Spinner /> Считаем…
        </p>
      )}
      {x?.error && <p className="text-bad">{x.error}</p>}
      {x && !x.error && (
        <div className="flex flex-col gap-2">
          <p className="flex items-baseline justify-between gap-2">
            <span className="font-semibold">{x.label}</span>
            <span className="text-2xl font-semibold text-accent">{x.value ?? "—"}</span>
          </p>
          <ul className="flex flex-col gap-1 border-t border-line pt-2">
            {x.parts?.map((p) => (
              <li key={p.label} className="flex justify-between gap-3">
                <span className="text-muted">{p.label}</span>
                <span className="tabular-nums">{p.value}</span>
              </li>
            ))}
          </ul>
          {x.note && <p className="text-xs text-muted">{x.note}</p>}
          {x.history && (
            <div className="border-t border-line pt-2">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted">Последние изменения</p>
              {x.history.length === 0 ? (
                <p className="text-xs text-muted">Пока ничего не случилось.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-xs">
                  {x.history.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
