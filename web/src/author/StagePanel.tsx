import type { PreparationView } from "../lib/api.gen";
import { STAGE_LABELS, STAGE_STATE_LABELS } from "../lib/authoring";

interface Props {
  view: PreparationView;
  busy: boolean;
  onPrepare(stage: string, regenerate: boolean): void;
  onAcceptStale(ref: string): void;
}

export default function StagePanel({ view, busy, onPrepare, onAcceptStale }: Props) {
  const stale = new Set(view.stale ?? []);
  return (
    <section aria-label="Этапы подготовки" className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {(view.stages ?? []).map((stage) => {
          const active = stage.status === "queued" || stage.status === "running";
          const dependents = [...stale].filter((ref) => ref.startsWith(`${stage.stage}:`));
          const state = dependents.length && stage.status === "ready" ? "stale" : stage.status;
          return (
            <li key={stage.stage} className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-raised p-3" data-stage={stage.stage} data-state={state}>
              <span className="font-medium text-ink">{STAGE_LABELS[stage.stage] ?? stage.stage}</span>
              <span className="text-sm text-muted" role="status">{STAGE_STATE_LABELS[state ?? ""] ?? state}</span>
              {stage.error_code && <span className="text-sm text-warn">код: {stage.error_code}</span>}
              <span className="ml-auto flex gap-2">
                <button className="btn min-h-11 px-3 text-sm" disabled={busy || active} onClick={() => onPrepare(stage.stage, false)} type="button">
                  {stage.status === "not_requested" ? "Подготовить" : "Повторить"}
                </button>
                {stage.status === "ready" && (
                  <button className="btn min-h-11 px-3 text-sm" disabled={busy} onClick={() => onPrepare(stage.stage, true)} type="button">Новый вариант</button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {stale.size > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="alert">
          <p className="mb-2 font-medium">Устаревшие результаты: публикация заблокирована, пока они не обновлены или приняты.</p>
          <ul className="flex flex-col gap-1">
            {[...stale].map((ref) => (
              <li key={ref} className="flex items-center gap-3">
                <code>{ref}</code>
                <button className="btn min-h-11 px-3 text-xs" disabled={busy} onClick={() => onAcceptStale(ref)} type="button">Принять как есть</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-sm text-muted">
        Расход: ${(view.spent_usd ?? 0).toFixed(3)}
        {view.budget_usd != null ? ` из $${view.budget_usd.toFixed(2)}` : ""}
        {view.cost_unknown ? " · стоимость части вызовов провайдер не сообщил (не считается нулём)" : ""}
      </p>
    </section>
  );
}
