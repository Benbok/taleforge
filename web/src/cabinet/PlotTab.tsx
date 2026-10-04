import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton, { Spinner } from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import WorldIntroPlayer from "../components/WorldIntroPlayer";
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
  plan?: Plot;
  revision?: { status?: string } | null;
  note?: string | null;
}

interface PlanOptions {
  structures: { id: string; name: string; description: string; best: boolean }[];
  estimate: { tokens_in: number; tokens_out: number; model: string; usd: number | null };
}

type Item = Record<string, unknown>;
export interface Plot {
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
export default function PlotTab({
  campaignId,
  packId,
}: {
  campaignId: string;
  packId?: string | null;
}) {
  const qc = useQueryClient();
  const [structure, setStructure] = useState("");
  const [note, setNote] = useState("");
  const plan = useQuery({
    queryKey: ["plan", campaignId],
    queryFn: () => api<PlanState>(`/api/campaigns/${campaignId}/plan`),
    refetchInterval: (q) =>
      q.state.data?.status === "generating" || q.state.data?.revision?.status === "revising" ? 4000 : false,
  });
  const p = plan.data;
  const options = useQuery({
    queryKey: ["plan-options", campaignId, structure],
    queryFn: () =>
      api<PlanOptions>(
        `/api/campaigns/${campaignId}/plan/options${structure ? `?structure_id=${encodeURIComponent(structure)}` : ""}`,
      ),
    enabled: !!p?.can_generate && p.status !== "generating",
  });

  if (plan.isError) {
    return (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось загрузить сюжетную арку: {(plan.error as Error).message}
      </div>
    );
  }

  if (!p) {
    return (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Изучение сюжетных свитков экспедиции…
      </div>
    );
  }

  const e = options.data?.estimate;

  const structureOptions: SelectOption[] = [
    {
      value: "",
      label: "Автоматически по анкете",
      sublabel: "Архитектор подберёт оптимальную структуру под выбранную тему",
      badge: "АВТО",
      badgeTone: "muted",
    },
    ...(options.data?.structures ?? []).map((s) => ({
      value: s.id,
      label: s.name,
      sublabel: s.description,
      badge: s.best ? "РЕКОМЕНДУЕТСЯ" : undefined,
      badgeTone: s.best ? ("accent" as const) : undefined,
    })),
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Poster */}
      {p.poster?.title && (
        <section className="card p-5 sm:p-6 border border-line bg-surface relative overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-line pb-3 mb-4">
            <span className="font-mono text-[11px] uppercase tracking-wider text-accent font-semibold">
              Афиша приключения · видят все игроки
            </span>
            {p.version && (
              <span className="font-mono text-xs text-muted">
                Вариант сюжета #{p.version}
              </span>
            )}
          </div>

          <h2 className="font-heading text-2xl sm:text-3xl font-bold text-ink">{p.poster.title}</h2>
          {p.poster.tagline && (
            <p className="mt-1 font-narration italic text-base sm:text-lg text-accent-hi">
              «{p.poster.tagline}»
            </p>
          )}

          {!!p.poster.tags?.length && (
            <div className="mt-3 flex flex-wrap gap-2">
              {p.poster.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-line bg-raised px-3 py-0.5 font-mono text-xs text-ink-2"
                >
                  {t}
                </span>
              ))}
            </div>
          )}

          {(!packId || packId === "echo-leviathans") && (
            <div className="mt-4">
              <WorldIntroPlayer />
            </div>
          )}

          {p.public_intro && (
            <div className="mt-4 rounded-[10px] border border-line/60 bg-raised/40 p-4 font-narration text-sm sm:text-base leading-relaxed text-ink-2 whitespace-pre-line">
              {p.public_intro}
            </div>
          )}
        </section>
      )}

      {/* Plot Status & Generation Card */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Генератор и статус сюжета</h2>
          {p.status === "generating" && (
            <span className="flex items-center gap-1.5 font-mono text-xs text-patina-hi">
              <Spinner /> генерация в фоне
            </span>
          )}
        </div>

        {p.status === "failed" ? (
          <div className="rounded-[8px] border border-bad/40 bg-bad/5 p-3 text-sm" role="alert">
            <p className="font-semibold text-bad">
              {STATUS_TEXT.failed}
              {p.error ? `: ${p.error}` : "."}
            </p>
            <p className="mt-1 text-muted">
              Пока сюжета нет, ИИ-мастер не начнёт игру. Запустите генерацию заново: можно сменить архетип или добавить
              пожелания.
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted" role="status">
            {p.status === "ready" ? `Сюжет готов (редакция ${p.version}).` : STATUS_TEXT[p.status]}
          </p>
        )}

        {p.revision?.status === "revising" && (
          <div className="rounded-[8px] border border-accent/40 bg-accent/10 p-3 font-mono text-xs text-accent">
            Акт завершён: ИИ-мастер пересматривает последующие акты с учётом принятых решений.
          </div>
        )}

        {p.revision?.status === "failed" && (
          <div className="rounded-[8px] border border-warn/40 bg-warn/10 p-3 font-mono text-xs text-warn">
            Пересмотр актов завершился сбоем: игра продолжается по текущему зафиксированному плану.
          </div>
        )}

        {!p.can_generate && p.status !== "generating" && (
          <p className="text-xs font-mono text-faint">
            Кампания уже началась: сюжетные ходы адаптируются ведущим динамически в реальном времени.
          </p>
        )}

        {p.can_generate && p.status !== "generating" && (
          <div className="flex flex-col gap-4 pt-2">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Структурный архетип сюжета">
                <CustomSelect
                  value={structure}
                  options={structureOptions}
                  onChange={setStructure}
                  ariaLabel="Структура сюжета"
                />
              </Field>

              <Field label="Пожелания к редакции" hint="Например «больше интриг», «динамичнее финал».">
                <input
                  className="field text-sm"
                  maxLength={500}
                  placeholder="Дополнительные акценты для архитектора..."
                  value={note}
                  onChange={(ev) => setNote(ev.target.value)}
                />
              </Field>
            </div>

            {e && (
              <div className="rounded-[8px] bg-raised/60 p-3 border border-line/60 font-mono text-xs text-muted flex items-center justify-between flex-wrap gap-2">
                <span>
                  Модель: <span className="text-ink font-semibold">{e.model}</span> (около{" "}
                  {Math.round((e.tokens_in + e.tokens_out) / 1000)} тыс. токенов)
                </span>
                <span className="text-accent font-semibold">
                  {e.usd != null ? `~$${e.usd.toFixed(2)}` : "локальная / бесплатно"}
                </span>
              </div>
            )}

            <div>
              <ActionButton
                primary
                className="font-mono text-xs tracking-wider"
                done="Архитектор сюжета приступил к работе"
                run={async () => {
                  const next = await api<PlanState>(`/api/campaigns/${campaignId}/plan`, {
                    body: { note: note.trim(), structure_id: structure || null },
                  });
                  setNote("");
                  qc.setQueryData(["plan", campaignId], next);
                }}
              >
                {p.status === "ready"
                  ? "СГЕНЕРИРОВАТЬ ДРУГОЙ ВАРИАНТ"
                  : p.status === "failed"
                    ? "СГЕНЕРИРОВАТЬ ЗАНОВО"
                    : "ПОДГОТОВИТЬ СЮЖЕТНУЮ АРКУ"}
              </ActionButton>
            </div>
          </div>
        )}
      </section>

      {/* Secret Plot Details for Master */}
      {p.plan?.title && <PlotDetails plot={p.plan} />}
    </div>
  );
}

const ACT_MARK: Record<string, string> = { active: "идёт сейчас", done: "завершён", pending: "впереди" };
const NODE_MARK: Record<string, string> = { done: "пройден", skipped: "обойдён" };
const s = (x: unknown) => (x == null ? "" : String(x));

/** Каркас целиком. Его видит только место мастера: сервер не отдаёт его владельцу-игроку. */
export function PlotDetails({ plot, open = false }: { plot: Plot; open?: boolean }) {
  return (
    <details className="card p-5 sm:p-6 border border-accent/40 bg-surface shadow-xl" open={open}>
      <summary className="cursor-pointer font-heading text-lg font-bold text-accent hover:text-accent-hi transition select-none flex items-center justify-between">
        <span>Сюжетный каркас целиком · Секретные материалы мастера</span>
        <span className="font-mono text-xs text-muted">развернуть ↓</span>
      </summary>

      <div className="mt-5 flex flex-col gap-5 text-sm border-t border-line pt-4">
        {/* Conflict & Stakes */}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-[8px] border border-line bg-raised/60 p-3">
            <span className="font-mono text-[10px] text-muted uppercase tracking-wider block">
              Основной конфликт
            </span>
            <p className="mt-1 font-semibold text-ink leading-snug">{plot.conflict}</p>
          </div>

          <div className="rounded-[8px] border border-line bg-raised/60 p-3">
            <span className="font-mono text-[10px] text-muted uppercase tracking-wider block">
              Ставки экспедиции
            </span>
            <p className="mt-1 font-semibold text-ink leading-snug">{plot.stakes}</p>
          </div>
        </div>

        {/* Antagonists */}
        <Block title="Антагонисты и план угрозы" items={plot.antagonists}>
          {(a) => {
            const threat = (a.threat as string[]) ?? [];
            const step = Number(a.threat_step ?? 0);
            return (
              <div className="flex flex-col gap-1.5 py-1">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-heading text-base font-bold text-ink">{s(a.name)}:</span>
                  <span className="text-ink-2">{s(a.goal)}</span>
                </div>
                <div className="font-mono text-xs text-muted">
                  <span className="text-warn">Слабость:</span> {s(a.weakness)} ·{" "}
                  <span className="text-accent">Тайна:</span> {s(a.secret)}
                </div>
                {threat.length > 0 && (
                  <div className="mt-1 rounded-[6px] bg-raised p-2 font-mono text-xs">
                    <span className="text-accent font-semibold block mb-1">
                      План угрозы (шаг {step} из {threat.length}):
                    </span>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {threat.map((t, i) => (
                        <span key={i} className="flex items-center gap-1">
                          <span
                            className={
                              i < step
                                ? "line-through text-muted"
                                : i === step
                                  ? "text-bad font-bold"
                                  : "text-ink-2"
                            }
                          >
                            {i + 1}. {t}
                          </span>
                          {i < threat.length - 1 && <span className="text-faint">→</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          }}
        </Block>

        {/* Acts */}
        <Block title="Акты приключения" items={plot.acts}>
          {(a) => (
            <div className="flex flex-col gap-1 py-1">
              <div className="flex items-center gap-2">
                <span className="font-heading text-base font-bold text-ink">{s(a.title)}</span>
                <Mark text={ACT_MARK[s(a.status)]} />
              </div>
              <p className="text-sm text-ink-2">{s(a.goal)}</p>
              {!!a.outcome && <span className="font-mono text-xs text-patina-hi">Итог: {s(a.outcome)}</span>}
              <ul className="mt-2 space-y-1.5 pl-4 border-l-2 border-line">
                {((a.nodes as Item[]) ?? []).map((n, i) => (
                  <li key={i} className="text-xs">
                    <span className="font-semibold text-ink">{s(n.title)}</span>{" "}
                    <Mark text={NODE_MARK[s(n.status)]} />: {s(n.summary)}
                    {!!n.outcome && <span className="block font-mono text-patina-hi">Итог: {s(n.outcome)}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Block>

        {/* Locations */}
        <Block title="Ключевые локации" items={plot.locations}>
          {(l) => (
            <div className="py-1">
              <span className="font-semibold text-ink">{s(l.name)}</span>
              {l.status === "developed" && <Mark text="развёрнуто" />}: {s(l.role)}{" "}
              <span className="font-mono text-xs text-accent">Секрет: {s(l.secret)}</span>
            </div>
          )}
        </Block>

        {/* NPCs */}
        <Block title="Персонажи ведущего (NPC)" items={plot.npcs}>
          {(n) => (
            <div className="py-1">
              <span className="font-semibold text-ink">{s(n.name)}</span>
              {n.status === "developed" && <Mark text="развёрнут" />}: {s(n.role)}; мотив: {s(n.want)}{" "}
              <span className="font-mono text-xs text-accent">Скрытое: {s(n.secret)}</span>
            </div>
          )}
        </Block>

        {/* Reveals */}
        <Block title="Тайны и зацепки" items={plot.reveals}>
          {(r) => (
            <div className="py-1">
              <span className="text-ink">{s(r.truth)}</span> {!!r.revealed && <Mark text="раскрыта" />}{" "}
              <span className="font-mono text-xs text-muted">
                ({((r.clues as unknown[]) ?? []).length} зацепки)
              </span>
            </div>
          )}
        </Block>

        {/* Endings */}
        <Block title="Возможные финалы" items={(plot.endings ?? []).map((e) => ({ e }))}>
          {(x) => <span className="text-ink-2 py-0.5 block">{s(x.e)}</span>}
        </Block>
      </div>
    </details>
  );
}

function Block({
  title,
  items,
  children,
}: {
  title: string;
  items?: Item[];
  children: (x: Item) => React.ReactNode;
}) {
  if (!items?.length) return null;
  return (
    <div className="flex flex-col gap-2 rounded-[10px] border border-line bg-raised/40 p-4">
      <h3 className="font-mono text-xs font-bold text-accent uppercase tracking-wider">{title}</h3>
      <div className="divide-y divide-line/60">
        {items.map((x, i) => (
          <div key={i} className="py-2 first:pt-0 last:pb-0">
            {children(x)}
          </div>
        ))}
      </div>
    </div>
  );
}

function Mark({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <span className="rounded bg-raised border border-line px-1.5 py-0.2 font-mono text-[10px] text-accent">
      {text}
    </span>
  );
}
