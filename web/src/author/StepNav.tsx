export type StepState = "done" | "partial" | "empty" | "running" | "problem" | "locked" | "stale";

export interface StepInfo {
  id: string;
  title: string;
  state: StepState;
  note: string;
}

const MARK: Record<StepState, string> = {
  done: "border-patina bg-patina text-on-accent",
  partial: "border-accent text-accent bg-accent/10",
  empty: "border-line text-muted bg-surface",
  running: "border-accent text-accent bg-accent/20 animate-pulse motion-reduce:animate-none",
  problem: "border-bad text-bad bg-bad/10",
  locked: "border-line-soft text-faint bg-surface/50 opacity-60",
  stale: "border-warn text-warn bg-warn/10",
};

interface Props {
  steps: StepInfo[];
  active: string;
  onSelect(id: string): void;
}

/** Порядок подготовки: шаги действительно идут друг за другом, поэтому они пронумерованы. */
export default function StepNav({ steps, active, onSelect }: Props) {
  const completedCount = steps.filter((s) => s.state === "done").length;

  return (
    <nav aria-label="Шаги подготовки" className="flex flex-col gap-3 lg:sticky lg:top-24">
      <div className="hidden rounded-xl border border-line-soft bg-surface p-3 lg:flex lg:flex-col lg:gap-1.5">
        <div className="flex items-center justify-between text-xs text-muted">
          <span className="font-medium uppercase tracking-wider">Прогресс</span>
          <span>{completedCount} из {steps.length}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-line-soft">
          <div
            className="h-full rounded-full bg-patina transition-all duration-300"
            style={{ width: `${(completedCount / steps.length) * 100}%` }}
          />
        </div>
      </div>

      <ol className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:gap-1.5 lg:overflow-visible">
        {steps.map((step, i) => {
          const current = step.id === active;
          return (
            <li key={step.id} className="shrink-0 lg:shrink">
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                data-state={step.state}
                onClick={() => onSelect(step.id)}
                className={`group flex min-h-12 w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-all focus-visible:outline-2 focus-visible:outline-accent ${
                  current
                    ? "border-accent bg-raised shadow-sm"
                    : "border-transparent bg-surface/40 hover:border-line hover:bg-raised"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-transform group-hover:scale-105 ${MARK[step.state]}`}
                >
                  {step.state === "done" ? "✓" : i + 1}
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className={`truncate text-sm font-medium ${current ? "text-ink" : "text-ink-2"}`}>
                    {step.title}
                  </span>
                  <span
                    className={`truncate text-xs ${
                      step.state === "problem"
                        ? "text-bad font-medium"
                        : step.state === "stale"
                        ? "text-warn font-medium"
                        : "text-muted"
                    }`}
                  >
                    {step.note}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
