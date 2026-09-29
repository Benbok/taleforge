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
  decide: "Решения мастера",
  narrate: "Повествование",
  parse: "Разбор реплик",
  summary: "Сводки сцен",
  review: "Проверка героев",
  plan: "Подготовка сюжета",
  replan: "Другой вариант сюжета",
  intro: "Вступление в игру",
  bonds: "Вопросы о связях",
  hook: "Связь героя с сюжетом",
  check: "Проверка связи с моделью",
  catchup: "Сводка пропущенного",
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
    <div className="flex flex-col gap-6" aria-label="Расходы на модели">
      {/* Header & Period switch */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
              Расходы и лимиты нейросетей
            </h2>
            <p className="mt-1 text-sm text-muted">
              {s?.scope === "all" ? "Все кампании и служебные вызовы платформы." : "Ваши кампании."}{" "}
              Локальные модели LM Studio бесплатны.
            </p>
          </div>

          <div className="self-start sm:self-center">
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
        </div>
      </section>

      {q.isError && (
        <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
          Не удалось загрузить данные расходов: {(q.error as Error).message}
        </div>
      )}

      {!s && !q.isError && (
        <div className="card p-8 text-center text-muted font-mono text-sm">
          Сбор и вычисление статистики расходов…
        </div>
      )}

      {s && (
        <>
          {/* Top 3 Big Stat Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card p-4 sm:p-5 relative overflow-hidden">
              <div className="font-mono text-[11px] uppercase tracking-wider text-muted">
                Потрачено за {days} дн.
              </div>
              <div className="mt-1.5 font-heading text-3xl sm:text-4xl font-bold text-accent tabular-nums">
                {usd(s.total.cost)}
              </div>
              <div className="mt-1 font-mono text-[11px] text-faint">
                внешние API (Claude, Gemini)
              </div>
            </div>

            <div className="card p-4 sm:p-5 relative overflow-hidden">
              <div className="font-mono text-[11px] uppercase tracking-wider text-muted">
                Обращений к моделям
              </div>
              <div className="mt-1.5 font-heading text-3xl sm:text-4xl font-bold text-patina-hi tabular-nums">
                {num.format(s.total.calls)}
              </div>
              <div className="mt-1 font-mono text-[11px] text-faint">
                {num.format(s.total.tokens_in)} вх. · {num.format(s.total.tokens_out)} исх. токенов
              </div>
            </div>

            <div className="card p-4 sm:p-5 relative overflow-hidden">
              <div className="font-mono text-[11px] uppercase tracking-wider text-muted">
                Ошибок и сбоев API
              </div>
              <div
                className={`mt-1.5 font-heading text-3xl sm:text-4xl font-bold tabular-nums ${
                  s.total.errors > 0 ? "text-ember" : "text-patina"
                }`}
              >
                {num.format(s.total.errors)}
              </div>
              <div className="mt-1 font-mono text-[11px] text-faint">
                {s.total.errors > 0 ? "зафиксированы отказы провайдеров" : "сбоев не зафиксировано"}
              </div>
            </div>
          </div>

          {/* Daily Expense Bar Chart */}
          <section className="card p-5 sm:p-6 border border-line bg-surface">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="font-heading text-base sm:text-lg font-bold text-ink">
                  Динамика расходов по дням
                </h3>
                <p className="text-xs text-muted">Высота столбика пропорциональна сумме расходов за день</p>
              </div>
              <span className="font-mono text-xs text-accent">
                Пик: {usd(peak)}
              </span>
            </div>

            {s.by_day.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted">
                За выбранный период обращений к платным моделям не было.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                <div
                  aria-label="По дням"
                  className="flex h-36 items-end gap-1.5 sm:gap-2 rounded-[8px] bg-raised/40 p-3 border border-line/60"
                >
                  {s.by_day.map((d) => {
                    const heightPct = Math.max(4, (d.cost / peak) * 100);
                    return (
                      <div
                        key={d.day}
                        className="group relative flex-1 h-full flex items-end justify-center"
                      >
                        <div
                          className="w-full rounded-t-[4px] bg-accent/70 group-hover:bg-accent transition-all cursor-pointer"
                          style={{ height: `${heightPct}%` }}
                        />
                        {/* Tooltip on hover */}
                        <div className="pointer-events-none absolute bottom-full mb-2 hidden group-hover:flex flex-col items-center z-20 whitespace-nowrap rounded-[6px] border border-line bg-raised px-2.5 py-1.5 text-xs shadow-lg">
                          <span className="font-mono text-accent font-semibold">{DAY.format(new Date(d.day))}</span>
                          <span className="font-mono text-ink tabular-nums">{usd(d.cost)}</span>
                          <span className="font-mono text-[10px] text-muted">{d.calls} запросов</span>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex justify-between font-mono text-[10px] text-faint px-1">
                  <span>{DAY.format(new Date(s.by_day[0].day))}</span>
                  <span>{DAY.format(new Date(s.by_day[s.by_day.length - 1].day))}</span>
                </div>
              </div>
            )}
          </section>

          {/* Campaign Spend Table */}
          {s.by_campaign.length > 0 && (
            <section className="card p-5 sm:p-6 border border-line bg-surface">
              <h3 className="font-heading text-lg font-bold text-ink mb-1">
                Расходы по кампаниям
              </h3>
              <p className="text-xs text-muted mb-4">
                Затраты за выбранный период и текущий статус лимита расходов
              </p>

              <div className="overflow-x-auto -mx-5 px-5 sm:mx-0 sm:px-0">
                <table className="w-full text-left text-sm min-w-[500px]">
                  <thead>
                    <tr className="border-b border-line text-xs font-mono text-muted uppercase tracking-wider">
                      <th className="pb-2 pr-4 font-normal">Кампания</th>
                      <th className="pb-2 pr-4 font-normal text-right">За период</th>
                      <th className="pb-2 font-normal">Лимит расходов</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {s.by_campaign.map((c) => (
                      <tr key={c.id || "none"} className="group hover:bg-raised/30 transition">
                        <td className="py-2.5 pr-4 font-medium">
                          {c.id ? (
                            <Link
                              to={`/c/${c.id}/manage?tab=settings`}
                              className="text-ink hover:text-accent font-semibold transition inline-flex items-center gap-1.5"
                            >
                              <span>{c.name ?? c.id}</span>
                              <span className="text-faint text-xs group-hover:text-accent">→</span>
                            </Link>
                          ) : (
                            <span className="text-muted">{c.name ?? "Служебные вызовы"}</span>
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-right font-mono text-ink font-semibold tabular-nums">
                          {usd(c.cost)}
                        </td>
                        <td className="py-2.5">
                          <Limit spent={c.spent_total} limit={c.limit} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Breakdown Grid: Models & Purposes */}
          <div className="grid gap-6 md:grid-cols-2">
            {s.by_model.length > 0 && (
              <section className="card p-5 sm:p-6 border border-line bg-surface">
                <h3 className="font-heading text-lg font-bold text-ink mb-1">
                  По моделям
                </h3>
                <p className="text-xs text-muted mb-4">Стоимость и объём обработанных токенов</p>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs font-mono text-muted uppercase tracking-wider">
                        <th className="pb-2 pr-2 font-normal">Модель</th>
                        <th className="pb-2 pr-2 font-normal text-right">Стоимость</th>
                        <th className="pb-2 font-normal text-right">Токены</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {s.by_model.map((m) => (
                        <tr key={m.model} className="hover:bg-raised/30 transition">
                          <td className="py-2 pr-2 font-mono text-xs text-ink-2 break-all">{m.model}</td>
                          <td className="py-2 pr-2 text-right font-mono text-ink font-semibold tabular-nums">
                            {usd(m.cost)}
                          </td>
                          <td className="py-2 text-right font-mono text-xs text-muted tabular-nums">
                            {num.format(m.tokens_in)} <span className="text-faint">вх.</span> →{" "}
                            {num.format(m.tokens_out)} <span className="text-faint">исх.</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {s.by_purpose.length > 0 && (
              <section className="card p-5 sm:p-6 border border-line bg-surface">
                <h3 className="font-heading text-lg font-bold text-ink mb-1">
                  По назначению
                </h3>
                <p className="text-xs text-muted mb-4">На какие игровые задачи ушли ресурсы</p>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs font-mono text-muted uppercase tracking-wider">
                        <th className="pb-2 pr-2 font-normal">Назначение</th>
                        <th className="pb-2 pr-2 font-normal text-right">Стоимость</th>
                        <th className="pb-2 font-normal text-right">Вызовов</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {s.by_purpose.map((p) => (
                        <tr key={p.purpose} className="hover:bg-raised/30 transition">
                          <td className="py-2 pr-2 text-ink">{PURPOSE[p.purpose] ?? p.purpose}</td>
                          <td className="py-2 pr-2 text-right font-mono text-ink font-semibold tabular-nums">
                            {usd(p.cost)}
                          </td>
                          <td className="py-2 text-right font-mono text-xs text-muted tabular-nums">
                            {p.calls}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Limit({ spent, limit }: { spent: number; limit: number | null }) {
  if (limit == null) {
    return (
      <span className="font-mono text-xs text-muted">
        без лимита · всего {usd(spent)}
      </span>
    );
  }
  const pct = limit > 0 ? Math.min(100, (spent / limit) * 100) : 100;
  const isExhausted = pct >= 100;
  const isWarning = pct >= 80 && !isExhausted;

  const barColor = isExhausted
    ? "bg-bad"
    : isWarning
      ? "bg-warn"
      : "bg-patina";

  return (
    <div className="flex flex-col gap-1 min-w-[130px] max-w-[220px]">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised">
        <div
          className={`h-full transition-all duration-300 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex items-center justify-between font-mono text-[11px] text-muted tabular-nums">
        <span>
          {usd(spent)} / {usd(limit)}
        </span>
        {isExhausted ? (
          <span className="font-bold text-bad">исчерпан</span>
        ) : (
          <span className="text-faint">{Math.round(pct)}%</span>
        )}
      </div>
    </div>
  );
}
