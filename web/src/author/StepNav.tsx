export type StepState = "done" | "partial" | "empty" | "running" | "problem" | "locked" | "stale";

export interface StepInfo {
  id: string;
  title: string;
  state: StepState;
  note: string;
}

const MARK: Record<StepState, string> = {
  done: "border-patina bg-patina text-on-accent",
  partial: "border-accent text-accent",
  empty: "border-line text-muted",
  running: "border-accent text-accent animate-pulse motion-reduce:animate-none",
  problem: "border-bad text-bad",
  locked: "border-line-soft text-faint",
  stale: "border-warn text-warn",
};

interface Props {
  steps: StepInfo[];
  active: string;
  onSelect(id: string): void;
}

/** Порядок подготовки: шаги действительно идут друг за другом, поэтому они пронумерованы. */
export default function StepNav({ steps, active, onSelect }: Props) {
  return (
    <nav aria-label="Шаги подготовки" className="lg:sticky lg:top-24">
      <ol className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:gap-1 lg:overflow-visible">
        {steps.map((step, i) => {
          const current = step.id === active;
          return (
            <li key={step.id} className="shrink-0 lg:shrink">
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                data-state={step.state}
                onClick={() => onSelect(step.id)}
                className={`flex min-h-11 w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                  current ? "border-accent bg-raised" : "border-transparent hover:bg-raised"
                }`}
              >
                <span aria-hidden="true" className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold ${MARK[step.state]}`}>
                  {step.state === "done" ? "✓" : i + 1}
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className={`truncate text-sm ${current ? "font-semibold text-ink" : "text-ink-2"}`}>{step.title}</span>
                  <span className={`truncate text-xs ${step.state === "problem" ? "text-bad" : step.state === "stale" ? "text-warn" : "text-muted"}`}>{step.note}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
