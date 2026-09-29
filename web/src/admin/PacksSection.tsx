import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { api, getToken } from "../lib/api";
import type { Pack } from "../lib/campaign";
import { toast } from "../stores/toasts";

interface UploadResult {
  ok: boolean;
  pack_id: string;
  version: string;
  summary: string;
  report: { warnings: string[]; customs: string[] };
  errors: string[];
  errors_total: number;
  imported: { id: string; version: string; state: string }[];
}

const DATE = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const ENTITY_LABELS: Record<string, string> = {
  classes: "Классы",
  subclasses: "Подклассы",
  races: "Происхождения",
  backgrounds: "Предыстории",
  spells: "Заклинания",
  monsters: "Чудовища",
  items: "Предметы",
  feats: "Черты",
  conditions: "Состояния",
  languages: "Языки",
  rules: "Правила",
  lore: "Записи лора",
};

async function send(file: File, dryRun: boolean): Promise<UploadResult> {
  const res = await fetch(`/api/admin/packs${dryRun ? "?dry_run=true" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/zip", Authorization: `Bearer ${getToken() ?? ""}` },
    body: file,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `ошибка сервера (${res.status})`);
  return data as UploadResult;
}

/** Пакеты сеттинга: что загружено и загрузка нового архивом. Сначала проверка, запись — только после неё. */
export default function PacksSection() {
  const qc = useQueryClient();
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => api<Pack[]>("/api/packs") });
  const [file, setFile] = useState<File | null>(null);
  const [checked, setChecked] = useState<UploadResult | null>(null);
  const [done, setDone] = useState<UploadResult | null>(null);

  return (
    <div className="flex flex-col gap-6" aria-label="Пакеты сеттинга">
      {/* Intro info box */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
              Пакеты сеттинга и правил
            </h2>
            <p className="mt-1 text-sm text-muted max-w-2xl leading-relaxed">
              Пакет задаёт лор, классы, происхождения, чудовищ, заклинания и тему оформления.
              Новые версии пакетов не нарушают уже идущие кампании — они продолжают работать на закреплённой версии.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
            <span>УСТАНОВЛЕНО:</span>
            <span className="font-bold text-accent">{packs.data?.length ?? 0}</span>
          </div>
        </div>
      </section>

      {/* Installed packs list */}
      <section className="flex flex-col gap-4">
        <div className="flex items-center justify-between px-1">
          <h3 className="font-heading text-lg font-semibold tracking-wide text-ink">
            Установленные пакеты
          </h3>
          {packs.isFetching && <span className="font-mono text-xs text-muted">Обновление…</span>}
        </div>

        {packs.isError && (
          <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
            Не удалось загрузить список: {(packs.error as Error).message}
          </div>
        )}

        {packs.isSuccess && packs.data.length === 0 && (
          <div className="card p-6 text-center text-muted">
            <p className="text-sm">Пакетов пока нет в системе.</p>
            <p className="mt-1 text-xs text-faint">Загрузите базовые правила SRD 5.1 первыми через форму ниже.</p>
          </div>
        )}

        <div className="grid gap-4">
          {(packs.data ?? []).map((p) => {
            const countsEntries = Object.entries(p.counts ?? {});
            return (
              <div
                key={`${p.id}@${p.version}`}
                className="card group relative overflow-hidden p-5 transition hover:border-accent/60"
              >
                {/* Two-tone header */}
                <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
                  <div className="flex items-baseline gap-2.5 flex-wrap">
                    <span className="font-heading text-lg font-bold text-ink group-hover:text-accent transition">
                      {p.name}
                    </span>
                    <span className="font-mono text-xs text-muted">({p.id})</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="rounded-[8px] border border-accent/40 bg-accent/10 px-2.5 py-0.5 font-mono text-xs font-semibold text-accent">
                      v{p.version}
                    </span>
                  </div>
                </div>

                {/* Body: import date & entity counts */}
                <div className="mt-3.5 flex flex-col gap-2.5">
                  {p.imported_at && (
                    <div className="font-mono text-[11px] text-faint flex items-center gap-1.5">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <polyline points="12 6 12 12 16 14" />
                      </svg>
                      <span>Загружен {DATE.format(new Date(p.imported_at))}</span>
                    </div>
                  )}

                  {countsEntries.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {countsEntries.map(([k, n]) => (
                        <span
                          key={k}
                          className="inline-flex items-center gap-1 rounded-md border border-line bg-raised px-2.5 py-1 font-mono text-xs text-ink-2"
                        >
                          <span className="text-muted">{ENTITY_LABELS[k] ?? k}:</span>
                          <span className="font-semibold text-accent">{n}</span>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-muted">Записей сущностей нет</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Upload pack dock */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div className="flex items-center gap-2">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--tf-accent)"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <h3 className="font-heading text-lg font-bold text-ink">Загрузить новый пакет</h3>
        </div>

        <p className="mt-1 text-xs sm:text-sm text-muted">
          Zip-архив папки пакета: файл <code className="text-accent font-mono text-xs">pack.yaml</code> должен
          находиться в корне архива или во вложенной папке первого уровня.
        </p>

        <div className="mt-4 flex flex-col gap-4">
          {/* Dropzone / File Picker Button */}
          <div className="rounded-[12px] border-2 border-dashed border-line bg-raised/30 p-5 transition hover:border-accent/60">
            <label className="flex flex-col sm:flex-row items-center justify-center gap-3 cursor-pointer text-center sm:text-left">
              <span className="btn btn-outline-copper text-xs font-mono tracking-wider">
                ВЫБРАТЬ .ZIP АРХИВ
              </span>
              <span className="text-xs sm:text-sm text-muted">
                {file ? (
                  <span className="font-mono text-ink font-semibold">
                    {file.name} · {Math.ceil(file.size / 1024)} КБ
                  </span>
                ) : (
                  "Файл архива не выбран"
                )}
              </span>
              <input
                type="file"
                className="sr-only"
                accept=".zip,application/zip"
                aria-label="Архив пакета"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setChecked(null);
                  setDone(null);
                }}
              />
            </label>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-3">
            <ActionButton
              className="text-xs sm:text-sm font-mono tracking-wider"
              run={async () => {
                if (!file) throw new Error("Выберите архив пакета");
                setDone(null);
                setChecked(await send(file, true));
              }}
            >
              1. ПРОВЕРИТЬ АРХИВ (DRY RUN)
            </ActionButton>

            {checked?.ok && !done && (
              <ActionButton
                primary
                className="text-xs sm:text-sm font-mono tracking-wider"
                run={async () => {
                  const r = await send(file!, false);
                  setDone(r);
                  await qc.invalidateQueries({ queryKey: ["packs"] });
                  if (r.imported.some((x) => x.state === "imported")) toast.ok("Пакет успешно загружен");
                  else toast.info("Такая версия уже загружена: изменений нет");
                }}
              >
                2. ЗАГРУЗИТЬ {checked.pack_id} v{checked.version}
              </ActionButton>
            )}

            {file && (
              <button
                type="button"
                className="btn px-3 py-1.5 text-xs text-muted hover:text-ink"
                onClick={() => {
                  setFile(null);
                  setChecked(null);
                  setDone(null);
                }}
              >
                Сбросить
              </button>
            )}
          </div>

          {/* Validation report */}
          {checked && <Report r={checked} />}

          {/* Done notification */}
          {done && (
            <div className="rounded-[10px] border border-patina/40 bg-patina/10 p-4">
              <h4 className="font-heading text-sm font-bold text-patina-hi">Результат импорта:</h4>
              <ul className="mt-2 flex flex-col gap-1 text-xs font-mono" role="status">
                {done.imported.map((x) => (
                  <li key={x.id} className={x.state === "imported" ? "text-patina" : "text-muted"}>
                    {x.id} v{x.version}: {x.state === "imported" ? "✓ Записан в базу" : "— Без изменений, такая версия уже есть"}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Report({ r }: { r: UploadResult }) {
  return (
    <div
      className={`flex flex-col gap-3 rounded-[12px] border p-4 text-sm ${
        r.ok ? "border-patina/40 bg-patina/5" : "border-bad/40 bg-bad/5"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
            r.ok ? "bg-patina text-bg" : "bg-bad text-ink"
          }`}
        >
          {r.ok ? "✓" : "!"}
        </span>
        <span className={`font-mono text-xs sm:text-sm font-semibold ${r.ok ? "text-patina-hi" : "text-bad"}`}>
          {r.ok ? "Проверка пройдена: пакет готов к установке" : `Проверка не пройдена: ошибок ${r.errors_total}`}
        </span>
      </div>

      {r.summary && (
        <pre className="max-h-60 overflow-x-auto rounded-[8px] border border-line bg-raised/80 p-3 font-mono text-xs text-ink-2">
          {r.summary}
        </pre>
      )}

      {r.errors.length > 0 && (
        <div className="rounded-[8px] border border-bad/30 bg-bad/10 p-3">
          <p className="font-mono text-xs font-bold text-bad uppercase tracking-wider mb-1.5">
            Критические ошибки:
          </p>
          <ul className="list-disc pl-5 text-xs text-bad space-y-1">
            {r.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
            {r.errors_total > r.errors.length && (
              <li className="font-mono">…и ещё {r.errors_total - r.errors.length}</li>
            )}
          </ul>
        </div>
      )}

      {r.report?.warnings?.length > 0 && (
        <div className="rounded-[8px] border border-warn/30 bg-warn/10 p-3">
          <p className="font-mono text-xs font-bold text-warn uppercase tracking-wider mb-1.5">
            Предупреждения:
          </p>
          <ul className="list-disc pl-5 text-xs text-warn space-y-1">
            {r.report.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
