import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../lib/api";
import { useGame } from "../stores/game";
import { TOOL_RU } from "./tools";

interface Call {
  tool: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  ok?: boolean;
  secret?: boolean;
  routed?: boolean;
  auto?: boolean;
}
interface Llm {
  purpose: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cost: number;
  error?: string | null;
  at?: string;
}
interface Turn {
  session_id: string | null;
  started_at: string | null;
  status: string;
  seq: [number | null, number | null];
  calls: Call[];
  combat: string[];
  audit?: { regenerated: boolean; stripped: string[] } | null;
  llm: Llm[];
  error?: string | null;
  advance?: string | null;
}
interface Live {
  tool: string;
  at: string;
  secret: boolean;
  result?: Record<string, unknown>;
}
interface Log {
  secrets_visible: boolean;
  turns: Turn[];
  service_llm: Llm[];
  /** Вызовы живого мастера: события вне ходов ИИ. */
  live?: Live[];
}

const STATUS: Record<string, string> = { done: "готово", failed: "сбой", running: "идёт" };
const PURPOSE: Record<string, string> = {
  decide: "решение",
  narrate: "повествование",
  parse: "разбор реплики",
  summary: "сводка",
  review: "проверка героя",
};
const TIME = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const time = (s?: string | null) => (s ? TIME.format(new Date(s)) : "");
const pairs = (o?: Record<string, unknown>) =>
  Object.entries(o ?? {})
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");

function CallLine({ c }: { c: Call }) {
  if (c.args === undefined)
    return (
      <li className="text-muted">
        {TOOL_RU[c.tool] ?? c.tool} — скрытое действие (содержимое в журнале отключено)
      </li>
    );
  return (
    <li className={c.secret ? "rounded bg-raised px-1" : ""}>
      <b>{TOOL_RU[c.tool] ?? c.tool}</b> <span className="text-muted">({pairs(c.args)})</span>{" "}
      {c.error ? (
        <span className="text-bad">✗ {c.error}</span>
      ) : c.result && Object.keys(c.result).length ? (
        <span>→ {pairs(c.result)}</span>
      ) : c.ok ? (
        <span className="text-ok">✓</span>
      ) : null}
      {c.secret && <span className="ml-1 text-xs text-muted">[скрыто]</span>}
      {c.routed && <span className="ml-1 text-xs text-muted">[сервер]</span>}
      {c.auto && <span className="ml-1 text-xs text-muted">[авто]</span>}
    </li>
  );
}

function LlmLine({ x }: { x: Llm }) {
  return (
    <li>
      {x.at && `${time(x.at)} · `}
      {PURPOSE[x.purpose] ?? x.purpose} · {x.model} · {x.tokens_in}→{x.tokens_out} ток. · {x.latency_ms} мс · ${x.cost.toFixed(4)}
      {x.error && <span className="text-bad"> ✗ {x.error}</span>}
    </li>
  );
}

/** Журнал мастера: ходы, вызовы инструментов, броски и обращения к модели. Сервер отдаёт его только администраторам. */
export default function MasterLog({ campaignId }: { campaignId: string }) {
  const q = useQuery({ queryKey: ["master-log", campaignId], queryFn: () => api<Log>(`/api/campaigns/${campaignId}/master-log`) });
  const stage = useGame((s) => s.masterStage);
  // мастер закончил ход — в журнале новая запись
  useEffect(() => {
    if (stage === null) void q.refetch();
  }, [stage]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isError) return <p className="text-sm text-bad">Журнал не загрузился: {(q.error as Error).message}</p>;
  if (!q.data) return <p className="text-sm text-muted">Загружаем журнал…</p>;
  const log = q.data;
  let session: string | null | undefined;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted">{log.secrets_visible ? "Скрытые броски и шёпот показаны" : "Скрытые действия без содержимого"}</span>
        <button className="btn px-2 py-0.5 text-xs" onClick={() => void q.refetch()} disabled={q.isFetching} aria-busy={q.isFetching}>
          {q.isFetching ? "Обновляем…" : "Обновить"}
        </button>
      </div>
      {!!log.live?.length && (
        <section>
          <h3 className="mb-1 text-xs uppercase tracking-wide text-muted">Действия вне ходов ИИ</h3>
          <ul className="flex flex-col gap-0.5">
            {log.live.map((x, i) => (
              <li key={i} className={x.secret ? "rounded bg-raised px-1" : ""}>
                <span className="text-muted">{time(x.at)}</span> <b>{TOOL_RU[x.tool] ?? x.tool}</b>
                {x.result && Object.keys(x.result).length > 0 && <span className="text-muted"> → {pairs(x.result)}</span>}
                {x.secret && <span className="ml-1 text-xs text-muted">[скрыто]</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {log.turns.length === 0 && !log.live?.length && <p className="text-muted">Мастер ещё не делал ходов.</p>}
      {log.turns.map((t, i) => {
        const cost = t.llm.reduce((a, x) => a + x.cost, 0);
        const head = session !== t.session_id;
        session = t.session_id;
        return (
          <div key={i}>
            {head && <p className="mt-2 text-xs text-muted">Сессия {t.session_id ?? "—"}</p>}
            <details open={t.status === "failed"} className="rounded-md border border-line p-2">
              <summary className={`cursor-pointer ${t.status === "failed" ? "text-bad" : ""}`}>
                {time(t.started_at)} · {STATUS[t.status] ?? t.status} · реплики {t.seq[0] ?? "—"}–{t.seq[1] ?? "—"} · вызовов {t.calls.length} · $
                {cost.toFixed(4)}
              </summary>
              <div className="mt-2 flex flex-col gap-1.5">
                {t.error && <p className="text-bad">{t.error}</p>}
                {t.advance && <p className="text-muted">Ход существ: {t.advance}</p>}
                {t.calls.length > 0 && (
                  <ul className="list-disc pl-5">
                    {t.calls.map((c, j) => (
                      <CallLine key={j} c={c} />
                    ))}
                  </ul>
                )}
                {t.combat.length > 0 && (
                  <ul className="list-disc pl-5 text-muted">
                    {t.combat.map((n, j) => (
                      <li key={j}>{n}</li>
                    ))}
                  </ul>
                )}
                {t.audit && (t.audit.regenerated || t.audit.stripped.length > 0) && (
                  <p className="text-muted">
                    Разметка: {t.audit.regenerated ? "текст переписан" : ""}
                    {t.audit.stripped.length ? `, снято: ${t.audit.stripped.join(", ")}` : ""}
                  </p>
                )}
                {t.llm.length > 0 && (
                  <ul className="list-disc pl-5 text-xs text-muted">
                    {t.llm.map((x, j) => (
                      <LlmLine key={j} x={x} />
                    ))}
                  </ul>
                )}
              </div>
            </details>
          </div>
        );
      })}
      {log.service_llm.length > 0 && (
        <details>
          <summary className="cursor-pointer text-muted">Служебные вызовы модели ({log.service_llm.length})</summary>
          <ul className="list-disc pl-5 text-xs text-muted">
            {log.service_llm.map((x, j) => (
              <LlmLine key={j} x={x} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
