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
  return (
    <div>
      <h3 className="font-heading text-sm text-muted">{title}</h3>
      <ul className="mt-1 flex flex-col gap-1 text-sm">
        {issues.map((issue, i) => (
          <li key={`${issue.code}-${issue.object_ref ?? i}-${i}`}>
            <code>{issue.code}</code>
            {issue.object_ref ? ` · ${issue.object_ref}` : ""}
            {issue.message ? ` — ${issue.message}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ValidationPanel({ report, publishIssues, publishError, busy, onValidate, onPublish }: Props) {
  return (
    <section aria-label="Проверка и публикация" className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <button className="btn min-h-11 px-3 text-sm" type="button" disabled={busy} onClick={onValidate}>Проверить</button>
        <button className="btn btn-primary min-h-11 px-3 text-sm" type="button" disabled={busy || !report} onClick={onPublish}>Опубликовать</button>
      </div>
      {report && (
        <p className="text-sm text-muted" role="status">
          Ревизия {report.source_revision}: ошибок {(report.errors ?? []).length}, предупреждений {(report.warnings ?? []).length}
        </p>
      )}
      {report && <Issues title="Ошибки" issues={report.errors ?? []} />}
      {report && <Issues title="Предупреждения" issues={report.warnings ?? []} />}
      {publishError && <p className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm" role="alert">Публикация отклонена: {publishError}</p>}
      {publishIssues && <Issues title="Причины отказа" issues={publishIssues} />}
    </section>
  );
}
