import type { ProgressItem } from "../lib/authoringProgress";

interface Props {
  items: ProgressItem[];
  title?: string;
  onJump?(key: string): void;
}

/** Что заполнено и чего не хватает. Незаполненный пункт ведёт к своему полю. */
export default function Checklist({ items, title = "Что заполнено", onJump }: Props) {
  const ok = items.filter((i) => i.ok).length;
  return (
    <section aria-label={title} className="rounded-xl border border-line bg-surface p-3">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="font-heading text-base text-ink">{title}</h3>
        <span className={`text-sm ${ok === items.length ? "text-ok" : "text-muted"}`}>{ok} из {items.length}</span>
      </div>
      <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-line-soft" aria-hidden="true">
        <div className="h-full rounded-full bg-patina transition-[width] duration-300" style={{ width: `${(ok / Math.max(items.length, 1)) * 100}%` }} />
      </div>
      <ul className="grid gap-1 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.key}>
            <button
              type="button"
              className="flex min-h-11 w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-raised focus-visible:outline-2 focus-visible:outline-accent"
              onClick={() => onJump?.(item.key)}
              data-ok={item.ok}
            >
              <span aria-hidden="true" className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${item.ok ? "border-patina bg-patina text-on-accent" : "border-warn"}`}>
                {item.ok ? "✓" : ""}
              </span>
              <span className="flex flex-col">
                <span className="text-ink">{item.label}</span>
                <span className={`text-xs ${item.ok ? "text-muted" : "text-warn"}`}>{item.detail}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
