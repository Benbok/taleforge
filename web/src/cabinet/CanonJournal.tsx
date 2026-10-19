import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { CanonJournalOut } from "../lib/api.gen";

/** Что мастер сам завёл в мир по ходу игры: находки, вещи, приметы, контейнеры, придуманные предметы. */
export default function CanonJournal({ campaignId }: { campaignId: string }) {
  const journal = useQuery({
    queryKey: ["canon-journal", campaignId],
    queryFn: () => api<CanonJournalOut>(`/api/campaigns/${campaignId}/canon-journal`),
  });
  const entries = journal.data?.entries ?? [];
  return (
    <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
      <div className="border-b border-line pb-3">
        <h2 className="font-heading text-xl font-bold text-ink">Что добавил мастер</h2>
        <p className="mt-0.5 text-xs text-muted">
          Вещи, приметы и контейнеры, которых не было в мире и которые мастер завёл по ходу игры. Они стали каноном кампании.
        </p>
      </div>
      {journal.isError ? (
        <p className="text-sm text-bad">Не удалось загрузить журнал.</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted">Пока мастер ничего не добавлял.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {entries.map((e) => (
            <li key={e.event_id} className="py-2.5 flex flex-col gap-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-heading font-bold text-ink">{e.name}</span>
                <span className="font-mono text-[11px] uppercase tracking-wider text-muted">{e.kind}</span>
              </div>
              {e.reason ? <p className="text-xs text-muted">{e.reason}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
