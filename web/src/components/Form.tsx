import type { ReactNode } from "react";

/** Поле формы: подпись, подсказка под ней и сам ввод. */
export function Field({ label, hint, children, className = "" }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-sm ${className}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

/** Несколько взаимоисключающих вариантов кнопками: видно всё сразу, выбор — одним нажатием. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T | "";
  options: [T, string][];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
      {options.map(([k, text]) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={value === k}
          className={`btn px-3 py-1 text-sm ${value === k ? "btn-primary" : ""}`}
          onClick={() => onChange(k)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

/** Вкладки страницы; содержимое рисует родитель по выбранной. */
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map(([t, text]) => (
        <button
          key={t}
          role="tab"
          aria-selected={value === t}
          className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm ${value === t ? "border-accent font-semibold text-ink" : "border-transparent text-muted hover:text-ink"}`}
          onClick={() => onChange(t)}
        >
          {text}
        </button>
      ))}
    </nav>
  );
}
