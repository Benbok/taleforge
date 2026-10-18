import { useMemo, useState } from "react";
import type { ProgressItem } from "../lib/authoringProgress";
import { checkAgainstSchema, parseLooseJson } from "../lib/jsonCheck";
import Checklist from "./Checklist";

interface Props {
  label: string;
  /** JSON Schema этапа: та же, что у модели. Без неё проверяется только разбор JSON. */
  schema?: Record<string, unknown> | null;
  /** Каким станет содержимое после вставки: для частичной вставки — слитое с текущим. */
  preview(value: Record<string, unknown>): ProgressItem[];
  applyLabel: string;
  busy: boolean;
  /** Ошибки сервера после попытки применить. */
  serverErrors?: string[];
  /** Частичная вставка разрешена: недостающее можно дозаполнить потом. */
  partial?: boolean;
  onApply(value: Record<string, unknown>): Promise<boolean> | boolean;
}

/** Вставка ответа внешней модели: разбор на лету, проверка по схеме, предпросмотр результата до сохранения. */
export default function JsonPaste({ label, schema, preview, applyLabel, busy, serverErrors, partial, onApply }: Props) {
  const [raw, setRaw] = useState("");
  const parsed = useMemo(() => parseLooseJson(raw), [raw]);
  const issues = useMemo(() => {
    if (!parsed.value || !schema) return [];
    const all = checkAgainstSchema(parsed.value, schema as never);
    // частичная вставка лора: отсутствующие разделы не ошибка, их можно дописать потом
    return partial ? all.filter((i) => !(i.message === "не заполнено" && !i.path.includes("."))) : all;
  }, [parsed.value, schema, partial]);
  const items = parsed.value ? preview(parsed.value) : [];

  return (
    <section aria-label={label} className="flex flex-col gap-3 rounded-xl border-2 border-dashed border-accent/50 bg-surface p-3">
      <label className="flex flex-col gap-1">
        <span className="font-heading text-base text-ink">{label}</span>
        <span className="text-sm text-muted">Вставьте ответ модели целиком — обёртку ```json и текст вокруг можно не убирать.</span>
        <textarea
          aria-label={label}
          className="min-h-36 rounded-lg border border-line bg-raised p-2 font-mono text-xs"
          placeholder='{ "overview": "…" }'
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          spellCheck={false}
        />
      </label>
      {parsed.error && <p className="text-sm text-bad" role="alert">{parsed.error}</p>}
      {parsed.value && (
        <>
          <Checklist title="После вставки" items={items} />
          {issues.length > 0 && (
            <div className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="status" aria-label="Расхождения со схемой">
              <p className="mb-1 font-medium">Расхождения со схемой: {issues.length}</p>
              <ul className="flex flex-col gap-0.5">
                {issues.slice(0, 12).map((i, n) => (
                  <li key={n}><code className="text-xs">{i.path}</code> — {i.message}</li>
                ))}
                {issues.length > 12 && <li>…и ещё {issues.length - 12}</li>}
              </ul>
            </div>
          )}
        </>
      )}
      {serverErrors && serverErrors.length > 0 && (
        <div className="rounded-lg border border-bad/40 bg-ember-bg p-3 text-sm" role="alert" aria-label="Ошибки сервера">
          <p className="mb-1 font-medium">Сервер не принял: исправьте и вставьте снова</p>
          <ul className="flex flex-col gap-0.5">{serverErrors.map((e, n) => <li key={n}>{e}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn btn-primary min-h-11 px-4 text-sm"
          type="button"
          disabled={busy || !parsed.value}
          onClick={async () => {
            if (parsed.value && (await onApply(parsed.value))) setRaw("");
          }}
        >
          {applyLabel}
        </button>
        {raw && <button className="btn min-h-11 px-3 text-sm" type="button" onClick={() => setRaw("")}>Очистить</button>}
      </div>
    </section>
  );
}
