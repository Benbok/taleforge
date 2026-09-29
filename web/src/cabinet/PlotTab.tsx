import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import type { Poster } from "../lib/campaign";

interface PlanState {
  status: "none" | "generating" | "ready" | "failed";
  error: string | null;
  version: number | null;
  versions: number;
  poster: Poster | null;
  public_intro: string;
  can_generate: boolean;
  /** Каркас целиком — только месту мастера. */
  plan?: Plot;
  revision?: { status?: string } | null;
  note?: string | null;
}

interface PlanOptions {
  structures: { id: string; name: string; description: string; best: boolean }[];
  estimate: { tokens_in: number; tokens_out: number; model: string; usd: number | null };
}

type Item = Record<string, unknown>;
interface Plot {
  title?: string;
  conflict?: string;
  stakes?: string;
  antagonists?: Item[];
  acts?: Item[];
  locations?: Item[];
  npcs?: Item[];
  reveals?: Item[];
  endings?: string[];
}

const STATUS_TEXT: Record<string, string> = {
  none: "Сюжет ещё не подготовлен. Архитектор построит каркас по анкете и лору мира: завязку, злодеев с планом угрозы, акты, места и тайны. Детали мастер допишет по ходу игры.",
  generating: "Архитектор готовит сюжет. Это может занять пару минут, страницу можно закрыть.",
  failed: "Не получилось подготовить сюжет",
};

/** Сюжет кампании: афиша для всех, подготовка и новый вариант — до начала игры, каркас — только мастеру. */
export default function PlotTab({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient();
  const [structure, setStructure] = useState("");
  const [note, setNote] = useState("");
  const plan = useQuery({
    queryKey: ["plan", campaignId],
    queryFn: () => api<PlanState>(`/api/campaigns/${campaignId}/plan`),
    // событие о готовности приходит в игру; здесь, пока идёт работа, просто переспрашиваем
    refetchInterval: (q) => (q.state.data?.status === "generating" || q.state.data?.revision?.status === "revising" ? 4000 : false),
  });
  const p = plan.data;
  const options = useQuery({
    queryKey: ["plan-options", campaignId, structure],
    queryFn: () => api<PlanOptions>(`/api/campaigns/${campaignId}/plan/options${structure ? `?structure_id=${encodeURIComponent(structure)}` : ""}`),
    enabled: !!p?.can_generate && p.status !== "generating",
  });

  if (plan.isError) return <p className="text-bad">Не удалось загрузить сюжет: {(plan.error as Error).message}</p>;
  if (!p) return <p className="text-muted">Загружаем…</p>;
  const e = options.data?.estimate;

  return (
    <div className="flex flex-col gap-4">
      {p.poster?.title && (
        <section className="card p-4">
          <p className="text-xs uppercase tracking-wide text-muted">Афиша, её видят все</p>
          <h2 className="font-heading text-xl">{p.poster.title}</h2>
          {p.poster.tagline && <p className="font-narration italic">{p.poster.tagline}</p>}
          {!!p.poster.tags?.length && (
            <p className="mt-2 flex flex-wrap gap-1.5">
              {p.poster.tags.map((t) => (
                <span key={t} className="rounded-full border border-line px-2 py-0.5 text-xs">
                  {t}
                </span>
              ))}
            </p>
          )}
          {p.public_intro && <p className="mt-3 whitespace-pre-line font-narration leading-relaxed text-muted">{p.public_intro}</p>}
        </section>
      )}

      <section className="card flex flex-col gap-3 p-4">
        <h2 className="text-base font-semibold">Сюжет</h2>
        <p className={p.status === "failed" ? "text-bad" : "text-muted"} role="status">
          {p.status === "ready" ? `Сюжет готов, вариант ${p.version}.` : STATUS_TEXT[p.status]}
          {p.status === "failed" && p.error ? `: ${p.error}` : ""}
        </p>
        {p.revision?.status === "revising" && <p className="text-sm text-muted">Акт закрыт: мастер пересматривает дальнейшие акты с учётом того, что уже случилось.</p>}
        {p.revision?.status === "failed" && <p className="text-sm text-muted">Пересмотреть дальнейшие акты не вышло: игра идёт по прежнему плану.</p>}
        {!p.can_generate && p.status !== "generating" && (
          <p className="text-sm text-muted">Игра уже началась: дальше сюжет меняется по ходу, а не заново.</p>
        )}
        {p.can_generate && p.status !== "generating" && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Шаблон сюжета">
                <select className="field" value={structure} onChange={(ev) => setStructure(ev.target.value)}>
                  <option value="">Автоматически по анкете</option>
                  {(options.data?.structures ?? []).map((s) => (
                    <option key={s.id} value={s.id} title={s.description}>
                      {s.name}
                      {s.best ? " — лучше всего подходит" : ""}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Пожелание к варианту" hint="Например «мрачнее», «короче».">
                <input className="field" maxLength={500} value={note} onChange={(ev) => setNote(ev.target.value)} />
              </Field>
            </div>
            {e && (
              <p className="text-xs text-muted">
                Примерно {Math.round((e.tokens_in + e.tokens_out) / 1000)} тыс. токенов на модели {e.model}
                {e.usd != null ? `, около $${e.usd.toFixed(2)}.` : ": цена неизвестна или модель локальная."} Если каркас не пройдёт
                проверку, будет до трёх попыток.
              </p>
            )}
            <div>
              <ActionButton
                primary
                done="Архитектор взялся за сюжет"
                run={async () => {
                  const next = await api<PlanState>(`/api/campaigns/${campaignId}/plan`, { body: { note: note.trim(), structure_id: structure || null } });
                  setNote("");
                  qc.setQueryData(["plan", campaignId], next);
                }}
              >
                {p.status === "ready" ? "Другой вариант" : "Подготовить сюжет"}
              </ActionButton>
            </div>
          </>
        )}
      </section>

      {p.plan?.title && <PlotDetails plot={p.plan} />}
    </div>
  );
}

const ACT_MARK: Record<string, string> = { active: "идёт", done: "пройден", pending: "впереди" };
const NODE_MARK: Record<string, string> = { done: "пройден", skipped: "обойдён" };
const s = (x: unknown) => (x == null ? "" : String(x));

/** Каркас целиком. Его видит только место мастера: сервер не отдаёт его владельцу-игроку. */
function PlotDetails({ plot }: { plot: Plot }) {
  return (
    <details className="card p-4">
      <summary className="cursor-pointer font-semibold">Каркас целиком · видит только мастер</summary>
      <div className="mt-3 flex flex-col gap-4 text-sm">
        <p>
          <b>Конфликт:</b> {plot.conflict} <b>Ставки:</b> {plot.stakes}
        </p>
        <Block title="Антагонисты" items={plot.antagonists}>
          {(a) => {
            const threat = (a.threat as string[]) ?? [];
            const step = Number(a.threat_step ?? 0);
            return (
              <>
                <b>{s(a.name)}</b>: {s(a.goal)}. Слабость: {s(a.weakness)}. Тайна: {s(a.secret)}
                <span className="block text-muted">
                  План угрозы, сделано {step} из {threat.length}:{" "}
                  {threat.map((t, i) => (
                    <span key={i} className={i < step ? "line-through" : ""}>
                      {i ? " → " : ""}
                      {t}
                    </span>
                  ))}
                </span>
              </>
            );
          }}
        </Block>
        <Block title="Акты" items={plot.acts}>
          {(a) => (
            <>
              <b>{s(a.title)}</b> <Mark text={ACT_MARK[s(a.status)]} /> — {s(a.goal)}
              {!!a.outcome && <span className="block text-muted">Итог: {s(a.outcome)}</span>}
              <ul className="mt-1 list-disc pl-5">
                {((a.nodes as Item[]) ?? []).map((n, i) => (
                  <li key={i}>
                    {s(n.title)} <Mark text={NODE_MARK[s(n.status)]} />: {s(n.summary)}
                    {!!n.outcome && <span className="block text-muted">Итог: {s(n.outcome)}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Block>
        <Block title="Места" items={plot.locations}>
          {(l) => (
            <>
              <b>{s(l.name)}</b>
              {l.status === "developed" && <Mark text="развёрнуто" />}: {s(l.role)} <span className="text-muted">Секрет: {s(l.secret)}</span>
            </>
          )}
        </Block>
        <Block title="NPC" items={plot.npcs}>
          {(n) => (
            <>
              <b>{s(n.name)}</b>
              {n.status === "developed" && <Mark text="развёрнут" />}: {s(n.role)}; хочет — {s(n.want)}{" "}
              <span className="text-muted">Тайна: {s(n.secret)}</span>
            </>
          )}
        </Block>
        <Block title="Тайны" items={plot.reveals}>
          {(r) => (
            <>
              {s(r.truth)} {!!r.revealed && <Mark text="раскрыта" />}{" "}
              <span className="text-muted">({((r.clues as unknown[]) ?? []).length} зацепки)</span>
            </>
          )}
        </Block>
        <Block title="Финалы" items={(plot.endings ?? []).map((e) => ({ e }))}>
          {(x) => s(x.e)}
        </Block>
      </div>
    </details>
  );
}

function Block({ title, items, children }: { title: string; items?: Item[]; children: (x: Item) => React.ReactNode }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="mb-1 font-semibold">{title}</h3>
      <ul className="list-disc pl-5">
        {items.map((x, i) => (
          <li key={i}>{children(x)}</li>
        ))}
      </ul>
    </div>
  );
}

function Mark({ text }: { text?: string }) {
  return text ? <span className="text-xs text-muted">[{text}]</span> : null;
}
