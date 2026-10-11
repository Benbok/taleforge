import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

interface Status {
  enabled: boolean;
  prepared: boolean;
  used_bytes: number;
  max_bytes: number;
  queue: Record<string, number>;
  jobs: { id: string; status: string; error: string | null; elapsed_seconds: number | null }[];
}

export default function SfxStatus() {
  const query = useQuery({ queryKey: ["sfx-status"], queryFn: () => api<Status>("/api/admin/sfx"), refetchInterval: 5000 });
  if (!query.data) return query.error ? <p className="text-xs text-bad">{query.error.message}</p> : null;
  const data = query.data;
  return <div className="rounded-lg border border-line p-3 flex flex-col gap-2">
    <h3 className="font-heading text-lg">Локальные звуковые эффекты</h3>
    <p className="text-xs text-muted">
      {data.enabled ? (data.prepared ? "Модель готова" : "Ожидание загрузки модели") : "Генерация выключена"}
      {` · В очереди: ${data.queue.queued ?? 0} · Генерируются: ${data.queue.running ?? 0} · Ошибки: ${data.queue.failed ?? 0}`}
    </p>
    <p className="text-xs text-muted">Хранилище: {(data.used_bytes / 1048576).toFixed(1)} / {(data.max_bytes / 1048576).toFixed(0)} МБ.
      Сохранённые результаты и регенерация доступны в настройках кампании.</p>
    <details><summary className="cursor-pointer text-xs">Последние задания</summary>
      <ul className="mt-2 text-xs text-muted">{data.jobs.map((job) => <li key={job.id}>
        {job.id} · {job.status}{job.elapsed_seconds != null && ` · ${job.elapsed_seconds.toFixed(1)} с`}
        {job.error && <span className="text-bad"> · {job.error}</span>}
      </li>)}</ul>
    </details>
  </div>;
}
