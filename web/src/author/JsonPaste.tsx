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
export default function JsonPaste({
  label,
  schema,
  preview,
  applyLabel,
  busy,
  serverErrors,
  partial,
  onApply,
}: Props) {
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
    <section
      aria-label={label}
      className="flex flex-col gap-4 rounded-2xl border-2 border-dashed border-accent/40 bg-surface p-4 sm:p-5 shadow-sm"
    >
      <label className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <span className="font-heading text-base font-semibold text-ink">{label}</span>
          <span className="text-xs text-muted">Поддерживается автоочистка markdown-разметки</span>
        </div>
        <span className="text-xs text-ink-2">
          Вставьте ответ модели целиком — обёртку ```json и текст вокруг можно не убирать.
        </span>
        <textarea
          aria-label={label}
          className="min-h-36 rounded-xl border border-line bg-raised p-3 font-mono text-xs text-ink transition-colors focus:border-accent focus:outline-none"
          placeholder='{ "overview": "…" }'
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          spellCheck={false}
        />
      </label>

      {parsed.error && (
        <div className="rounded-xl border border-bad/40 bg-ember-bg p-3 text-sm text-bad" role="alert">
          <span className="font-semibold">Ошибка структуры JSON:</span> {parsed.error}
        </div>
      )}

      {parsed.value && (
        <>
          <Checklist title="После вставки" items={items} />
          {issues.length > 0 && (
            <div
              className="rounded-xl border border-warn/40 bg-warn/10 p-3.5 text-sm text-warn"
              role="status"
              aria-label="Расхождения со схемой"
            >
              <p className="mb-1.5 font-semibold">Расхождения со схемой: {issues.length}</p>
              <ul className="flex flex-col gap-1 text-xs">
                {issues.slice(0, 12).map((i, n) => (
                  <li key={n} className="flex items-baseline gap-1.5">
                    <code className="rounded bg-surface px-1 py-0.5 font-mono text-ink">{i.path}</code>
                    <span>— {i.message}</span>
                  </li>
                ))}
                {issues.length > 12 && (
                  <li className="text-muted">…и ещё {issues.length - 12} расхождений</li>
                )}
              </ul>
            </div>
          )}
        </>
      )}

      {serverErrors && serverErrors.length > 0 && (
        <div
          className="rounded-xl border border-bad/40 bg-ember-bg p-3.5 text-sm text-bad"
          role="alert"
          aria-label="Ошибки сервера"
        >
          <p className="mb-1.5 font-semibold">Сервер не принял: исправьте и вставьте снова</p>
          <ul className="flex flex-col gap-1 text-xs list-disc list-inside">
            {serverErrors.map((e, n) => (
              <li key={n}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          className="btn btn-primary min-h-11 px-5 text-sm font-semibold"
          type="button"
          disabled={busy || !parsed.value}
          onClick={async () => {
            if (parsed.value && (await onApply(parsed.value))) setRaw("");
          }}
        >
          {applyLabel}
        </button>
        {raw && (
          <button
            className="btn min-h-11 px-3 text-sm"
            type="button"
            onClick={() => setRaw("")}
          >
            Очистить
          </button>
        )}
      </div>
    </section>
  );
}
