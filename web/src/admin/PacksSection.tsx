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

const DATE = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" });

async function send(file: File, dryRun: boolean): Promise<UploadResult> {
  // тело запроса — сам архив: без multipart и лишних зависимостей на сервере
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
    <section className="card flex flex-col gap-4 p-4" aria-label="Пакеты сеттинга">
      <div>
        <h2 className="text-base font-semibold">Пакеты сеттинга</h2>
        <p className="text-sm text-muted">
          Пакет задаёт лор, классы, происхождения, чудовищ и тему оформления. Новая версия пакета не меняет кампании, которые уже идут на старой.
        </p>
      </div>
      {packs.isError && <p className="text-bad">Не удалось загрузить список: {(packs.error as Error).message}</p>}
      {packs.isSuccess && packs.data.length === 0 && <p className="text-sm text-muted">Пакетов пока нет. Загрузите базовые правила SRD первыми.</p>}
      <ul className="flex flex-col divide-y divide-line">
        {(packs.data ?? []).map((p) => (
          <li key={`${p.id}@${p.version}`} className="py-2 text-sm">
            <span className="font-semibold">{p.name}</span> <span className="text-muted">{p.id} · версия {p.version}</span>
            <span className="block text-xs text-muted">
              {p.imported_at && `загружен ${DATE.format(new Date(p.imported_at))} · `}
              {Object.entries(p.counts ?? {})
                .map(([k, n]) => `${k}: ${n}`)
                .join(", ") || "записей нет"}
            </span>
          </li>
        ))}
      </ul>

      <div className="flex flex-col gap-3 rounded-md border border-line p-3">
        <h3 className="font-semibold">Загрузить пакет</h3>
        <p className="text-xs text-muted">
          Zip-архив папки пакета: pack.yaml в корне архива или в одной папке. Зависимости — только из пакетов, которые идут с сервером.
        </p>
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <span className="btn">Выбрать архив</span>
          <span className={file ? "" : "text-muted"}>{file ? `${file.name} · ${Math.ceil(file.size / 1024)} КБ` : "архив не выбран"}</span>
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
        <div className="flex flex-wrap items-start gap-2">
          <ActionButton
            run={async () => {
              if (!file) throw new Error("Выберите архив пакета");
              setDone(null);
              setChecked(await send(file, true));
            }}
          >
            Проверить
          </ActionButton>
          {checked?.ok && !done && (
            <ActionButton
              primary
              run={async () => {
                const r = await send(file!, false);
                setDone(r);
                await qc.invalidateQueries({ queryKey: ["packs"] });
                if (r.imported.some((x) => x.state === "imported")) toast.ok("Пакет загружен");
                else toast.info("Такая версия уже загружена: ничего не изменилось");
              }}
            >
              Загрузить {checked.pack_id} {checked.version}
            </ActionButton>
          )}
        </div>
        {checked && <Report r={checked} />}
        {done && (
          <ul className="text-sm" role="status">
            {done.imported.map((x) => (
              <li key={x.id} className={x.state === "imported" ? "text-ok" : "text-muted"}>
                {x.id} {x.version}: {x.state === "imported" ? "записан" : "без изменений, такая версия уже есть"}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Report({ r }: { r: UploadResult }) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className={r.ok ? "text-ok" : "text-bad"}>
        {r.ok ? "Проверка пройдена" : `Проверка не пройдена: ошибок ${r.errors_total}`}
      </p>
      <pre className="overflow-x-auto rounded-md bg-raised p-2 text-xs">{r.summary}</pre>
      {r.errors.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-bad">
          {r.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
          {r.errors_total > r.errors.length && <li>…и ещё {r.errors_total - r.errors.length}</li>}
        </ul>
      )}
      {r.report.warnings.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-warn">
          {r.report.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
