import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Segmented } from "../components/Form";
import { api } from "../lib/api";

interface Totals {
  cost: number;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  errors: number;
}
interface Spend {
  days: number;
  scope: "all" | "own";
  total: Totals;
  by_day: (Totals & { day: string })[];
  by_campaign: (Totals & { id: string; name: string | null; limit: number | null; spent_total: number })[];
  by_model: (Totals & { model: string })[];
  by_purpose: (Totals & { purpose: string })[];
}

const PURPOSE: Record<string, string> = {
  decide: "решения мастера",
  narrate: "повествование",
  parse: "разбор реплик",
  summary: "сводки",
  review: "проверка героев",
  plan: "подготовка сюжета",
  replan: "другой вариант сюжета",
  intro: "вступление",
  bonds: "вопросы о связях",
  hook: "связь героя с сюжетом",
  check: "проверка моделей",
  catchup: "сводка пропущенного",
};
const usd = (x: number) => `$${x < 1 ? x.toFixed(4) : x.toFixed(2)}`;
const num = new Intl.NumberFormat("ru-RU");
const DAY = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });

/** Расходы на модели: за сколько, где и на что. Admin видит свои кампании, Super Admin — все. */
export default function SpendSection() {
  const [days, setDays] = useState("30");
  const q = useQuery({ queryKey: ["spend", days], queryFn: () => api<Spend>(`/api/admin/spend?days=${days}`) });
  const s = q.data;
  const peak = Math.max(0.000001, ...(s?.by_day.map((d) => d.cost) ?? [0]));

  return (
    <section className="card flex flex-col gap-4 p-4" aria-label="Расходы на модели">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">Расходы на модели</h2>
          <p className="text-sm text-muted">{s?.scope === "all" ? "Все кампании и служебные вызовы." : "Ваши кампании."} Локальные модели бесплатны.</p>
        </div>
        <Segmented
          label="Период"
          value={days}
          options={[
            ["7", "7 дней"],
            ["30", "30 дней"],
            ["90", "90 дней"],
          ]}
          onChange={setDays}
        />
      </div>
      {q.isError && <p className="text-bad">Не удалось загрузить расходы: {(q.error as Error).message}</p>}
      {!s && !q.isError && <p className="text-muted">Считаем…</p>}
      {s && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Big label="Потрачено" value={usd(s.total.cost)} />
            <Big label="Обращений" value={num.format(s.total.calls)} />
            <Big label="Сбоев" value={num.format(s.total.errors)} tone={s.total.errors ? "text-warn" : undefined} />
          </div>
          {s.by_day.length === 0 ? (
            <p className="text-sm text-muted">За этот период к моделям не обращались.</p>
          ) : (
            <div aria-label="По дням" className="flex h-28 items-end gap-1 border-b border-line">
              {s.by_day.map((d) => (
                <div
                  key={d.day}
                  className="min-w-1 flex-1 rounded-t bg-accent/70"
                  style={{ height: `${Math.max(3, (d.cost / peak) * 100)}%` }}
                  title={`${DAY.format(new Date(d.day))}: ${usd(d.cost)}, обращений ${d.calls}`}
                />
              ))}
            </div>
          )}
          {s.by_campaign.length > 0 && (
            <Table title="По кампаниям" head={["Кампания", "За период", "Лимит"]}>
              {s.by_campaign.map((c) => (
                <tr key={c.id || "none"}>
                  <td className="py-1 pr-2">{c.id ? <Link to={`/c/${c.id}/manage?tab=settings`}>{c.name ?? c.id}</Link> : <span className="text-muted">{c.name}</span>}</td>
                  <td className="py-1 pr-2 tabular-nums">{usd(c.cost)}</td>
                  <td className="py-1">
                    <Limit spent={c.spent_total} limit={c.limit} />
                  </td>
                </tr>
              ))}
            </Table>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {s.by_model.length > 0 && (
              <Table title="По моделям" head={["Модель", "Стоимость", "Токены"]}>
                {s.by_model.map((m) => (
                  <tr key={m.model}>
                    <td className="break-all py-1 pr-2">{m.model}</td>
                    <td className="py-1 pr-2 tabular-nums">{usd(m.cost)}</td>
                    <td className="py-1 text-xs text-muted tabular-nums">
                      {num.format(m.tokens_in)} → {num.format(m.tokens_out)}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
            {s.by_purpose.length > 0 && (
              <Table title="На что" head={["Назначение", "Стоимость", "Обращений"]}>
                {s.by_purpose.map((p) => (
                  <tr key={p.purpose}>
                    <td className="py-1 pr-2">{PURPOSE[p.purpose] ?? p.purpose}</td>
                    <td className="py-1 pr-2 tabular-nums">{usd(p.cost)}</td>
                    <td className="py-1 tabular-nums">{p.calls}</td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function Big({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

function Limit({ spent, limit }: { spent: number; limit: number | null }) {
  if (limit == null) return <span className="text-xs text-muted">нет · всего {usd(spent)}</span>;
  const pct = limit > 0 ? Math.min(100, (spent / limit) * 100) : 100;
  const tone = pct >= 100 ? "var(--color-bad)" : pct >= 80 ? "var(--color-warn)" : "var(--color-ok)";
  return (
    <span className="block min-w-28" title={pct >= 100 ? "Лимит исчерпан: мастер молчит" : undefined}>
      <span className="block h-1.5 overflow-hidden rounded-full bg-raised">
        <span className="block h-full" style={{ width: `${pct}%`, background: tone }} />
      </span>
      <span className="text-xs text-muted tabular-nums">
        {usd(spent)} из {usd(limit)}
        {pct >= 100 && <span className="text-bad"> · исчерпан</span>}
      </span>
    </span>
  );
}

function Table({ title, head, children }: { title: string; head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs text-muted">
            {head.map((h) => (
              <th key={h} className="pb-1 pr-2 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
