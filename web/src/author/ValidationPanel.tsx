import type { ValidationIssue, ValidationReport } from "../lib/api.gen";

interface Props {
  report: ValidationReport | null;
  publishIssues: ValidationIssue[] | null;
  publishError: string | null;
  busy: boolean;
  onValidate(): void;
  onPublish(): void;
}

function Issues({ title, issues }: { title: string; issues: ValidationIssue[] }) {
  if (!issues.length) return null;
  const isBlocking = title === "Ошибки" || title === "Причины отказа";

  return (
    <div className={`rounded-xl border p-4 ${isBlocking ? "border-bad/40 bg-ember-bg/60" : "border-warn/40 bg-warn/10"}`}>
      <h3 className={`font-heading text-sm font-semibold ${isBlocking ? "text-bad" : "text-warn"}`}>{title}</h3>
      <ul className="mt-2 flex flex-col gap-2 text-sm">
        {issues.map((issue, i) => (
          <li
            key={`${issue.code}-${issue.object_ref ?? i}-${i}`}
            className="flex flex-wrap items-baseline gap-2 rounded-lg border border-line-soft bg-surface/70 p-2"
          >
            <code className="rounded bg-line-soft px-1.5 py-0.5 text-xs font-semibold text-ink">{issue.code}</code>
            {issue.object_ref && (
              <span className="text-xs font-mono text-muted">· {issue.object_ref}</span>
            )}
            {issue.message && (
              <span className="text-sm text-ink-2">— {issue.message}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ValidationPanel({
  report,
  publishIssues,
  publishError,
  busy,
  onValidate,
  onPublish,
}: Props) {
  const errorCount = (report?.errors ?? []).length;
  const warningCount = (report?.warnings ?? []).length;
  const canPublish = report !== null && errorCount === 0;

  return (
    <section aria-label="Проверка и публикация" className="flex flex-col gap-5">
      {/* Pre-flight Status Card */}
      <div className="rounded-2xl border border-line bg-surface p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h3 className="font-heading text-base font-semibold text-ink">Предрелизная проверка мира</h3>
            <p className="text-xs text-muted">
              Проверяет целостность геометрии карт, достижимость локаций, связность сюжета и актуальность всех сущностей перед публикацией.
            </p>
          </div>
          {report && (
            <span
              className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${
                errorCount === 0
                  ? "bg-patina/20 text-patina"
                  : "bg-bad/20 text-bad"
              }`}
            >
              {errorCount === 0 ? "Готово к релизу" : `Ошибок: ${errorCount}`}
            </span>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line-soft pt-4">
          <button
            className="btn min-h-11 px-4 text-sm font-medium"
            type="button"
            disabled={busy}
            onClick={onValidate}
          >
            {busy ? "Проверяю…" : "Проверить"}
          </button>
          <button
            className={`btn min-h-11 px-5 text-sm font-semibold ${
              canPublish ? "btn-primary shadow-sm" : ""
            }`}
            type="button"
            disabled={busy || !report}
            onClick={onPublish}
          >
            Опубликовать
          </button>
        </div>
      </div>

      {report && (
        <p className="text-sm text-muted" role="status">
          Ревизия {report.source_revision}: ошибок {errorCount}, предупреждений {warningCount}
        </p>
      )}

      {report && <Issues title="Ошибки" issues={report.errors ?? []} />}
      {report && <Issues title="Предупреждения" issues={report.warnings ?? []} />}

      {publishError && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm text-warn" role="alert">
          <p className="font-semibold">Публикация отклонена: {publishError}</p>
        </div>
      )}

      {publishIssues && <Issues title="Причины отказа" issues={publishIssues} />}
    </section>
  );
}
