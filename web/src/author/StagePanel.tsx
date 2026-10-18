import type { PreparationView } from "../lib/api.gen";
import { STAGE_LABELS, STAGE_STATE_LABELS, UPSTREAM } from "../lib/authoring";

interface Props {
  view: PreparationView;
  busy: boolean;
  onPrepare(stage: string, regenerate: boolean): void;
  onAcceptStale(ref: string): void;
}

const DONE = new Set(["ready", "manual"]);

export default function StagePanel({ view, busy, onPrepare, onAcceptStale }: Props) {
  const stale = new Set(view.stale ?? []);
  const stages = view.stages ?? [];
  const statusOf = (name: string) => stages.find((s) => s.stage === name)?.status ?? "not_requested";
  const worldBuilt = DONE.has(statusOf("materialize"));

  const run = (stage: string, regenerate: boolean) => {
    // новый сюжет заменяет каркас: построенные под старый места, NPC и карты будут удалены
    if (stage === "plot" && worldBuilt && !window.confirm("Новый сюжет удалит уже созданные места, NPC и карты. Продолжить?")) return;
    onPrepare(stage, regenerate);
  };

  return (
    <section aria-label="Этапы подготовки" className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {stages.map((stage) => {
          const active = stage.status === "queued" || stage.status === "running";
          const isStale = stale.has(`stage:${stage.stage}`) && DONE.has(stage.status ?? "");
          const state = isStale ? "stale" : stage.status ?? "not_requested";
          const upstream = UPSTREAM[stage.stage];
          const waiting = upstream && !DONE.has(statusOf(upstream)) ? upstream : null;
          return (
            <li key={stage.stage} className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-raised p-3" data-stage={stage.stage} data-state={state}>
              <span className="font-medium text-ink">{STAGE_LABELS[stage.stage] ?? stage.stage}</span>
              <span className={`text-sm ${state === "stale" ? "text-warn" : "text-muted"}`} role="status">{STAGE_STATE_LABELS[state] ?? state}</span>
              {stage.error_code && <span className="text-sm text-warn">код: {stage.error_code}</span>}
              {waiting && <span className="text-sm text-muted">сначала: {STAGE_LABELS[waiting]}</span>}
              <span className="ml-auto flex gap-2">
                {state === "not_requested" && (
                  <button className="btn min-h-11 px-3 text-sm" disabled={busy || !!waiting} onClick={() => run(stage.stage, false)} type="button">Подготовить</button>
                )}
                {/* неудачная или устаревшая попытка повторяется новой работой: прежний результат её не подменяет */}
                {(state === "failed" || state === "blocked" || state === "stale") && (
                  <button className="btn min-h-11 px-3 text-sm" disabled={busy || active || !!waiting} onClick={() => run(stage.stage, true)} type="button">Повторить</button>
                )}
                {(state === "ready" || state === "manual") && (
                  <button className="btn min-h-11 px-3 text-sm" disabled={busy || !!waiting} onClick={() => run(stage.stage, true)} type="button">Новый вариант</button>
                )}
                {state === "stale" && (
                  <button className="btn min-h-11 px-3 text-sm" disabled={busy} onClick={() => onAcceptStale(`stage:${stage.stage}`)} type="button">Оставить как есть</button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {[...stale].filter((r) => !r.startsWith("stage:")).length > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="alert">
          <p className="mb-2 font-medium">Устаревшие результаты: публикация заблокирована, пока они не обновлены или приняты.</p>
          <ul className="flex flex-col gap-1">
            {[...stale].filter((r) => !r.startsWith("stage:")).map((ref) => (
              <li key={ref} className="flex items-center gap-3">
                <code>{ref}</code>
                <button className="btn min-h-11 px-3 text-xs" disabled={busy} onClick={() => onAcceptStale(ref)} type="button">Принять как есть</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-sm text-muted">
        Расход: ${(view.spent_usd ?? 0).toFixed(4)}
        {view.budget_usd != null ? ` из $${view.budget_usd.toFixed(2)}` : ""}
        {view.cost_unknown ? " · стоимость части вызовов провайдер не сообщил (не считается нулём)" : ""}
      </p>
    </section>
  );
}
