import type { ProgressItem } from "../lib/authoringProgress";

interface Props {
  items: ProgressItem[];
  title?: string;
  onJump?(key: string): void;
}

/** Что заполнено и чего не хватает. Незаполненный пункт ведёт к своему полю. */
export default function Checklist({ items, title = "Что заполнено", onJump }: Props) {
  const mandatory = items.filter((i) => !i.optional);
  const ok = mandatory.filter((i) => i.ok).length;
  const isComplete = ok === mandatory.length && mandatory.length > 0;

  return (
    <section aria-label={title} className="rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h3 className="font-heading text-base font-semibold text-ink">{title}</h3>
        <span className={`text-xs font-bold ${isComplete ? "text-ok" : "text-muted"}`}>
          {ok} из {mandatory.length} {isComplete ? "✓ готово" : ""}
        </span>
      </div>
      <div className="mb-3.5 h-2 overflow-hidden rounded-full bg-line-soft" aria-hidden="true">
        <div
          className={`h-full rounded-full transition-all duration-300 ${isComplete ? "bg-patina" : "bg-accent"}`}
          style={{ width: `${(ok / Math.max(mandatory.length, 1)) * 100}%` }}
        />
      </div>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className={`flex min-h-11 w-full items-start gap-2.5 rounded-xl border p-2 text-left text-sm transition-all focus-visible:outline-2 focus-visible:outline-accent ${
                item.ok
                  ? "border-line-soft bg-surface hover:border-line hover:bg-raised"
                  : "border-warn/30 bg-warn/5 hover:border-warn hover:bg-warn/10"
              }`}
              onClick={() => onJump?.(item.key)}
              data-ok={item.ok}
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${
                  item.ok
                    ? "border-patina bg-patina text-on-accent"
                    : "border-warn/60 text-warn"
                }`}
              >
                {item.ok ? "✓" : "!"}
              </span>
              <span className="flex flex-col min-w-0">
                <span className="truncate font-medium text-ink">{item.label}</span>
                <span className={`text-xs truncate ${item.ok ? "text-muted" : "text-warn font-medium"}`}>
                  {item.detail}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
