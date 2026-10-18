import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import type { DraftPatch, EditProposal, PreparationView, StageStatus, ValidationIssue, ValidationReport } from "../lib/api.gen";
import { authoring, authorKeys, newRequestKey, STAGE_STATE_LABELS } from "../lib/authoring";
import { done, loreProgress, plotProgress, type ProgressItem } from "../lib/authoringProgress";
import Checklist from "./Checklist";
import ContentEditor, { type DraftContent } from "./ContentEditor";
import GeographyView from "./GeographyView";
import JsonPaste from "./JsonPaste";
import LoreEditor, { type Lore } from "./LoreEditor";
import MapPreview from "./MapPreview";
import StepNav, { type StepInfo, type StepState } from "./StepNav";
import TaskBox from "./TaskBox";
import ValidationPanel from "./ValidationPanel";
import WorldOverview from "./WorldOverview";

const LORE_KEYS = ["overview", "era_and_magic", "regions", "history", "factions", "figures", "current_situation", "mysteries", "tone", "taboos"];
const PLOT_TEXT: [string, string][] = [
  ["title", "Название"],
  ["tagline", "Слоган"],
  ["public_intro", "Завязка для игроков"],
  ["conflict", "Конфликт"],
  ["stakes", "Ставки"],
];
const DONE = new Set(["ready", "manual"]);
type Plot = Record<string, unknown> & {
  regions?: { id: string; name: string }[];
  locations?: { id: string; name: string; region?: string | null }[];
  routes?: { ref: string; from: string; to: string }[];
};

function remembered(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* приватный режим: выбор живёт до перезагрузки */
  }
}

function jump(prefix: string, key: string) {
  document.getElementById(`${prefix}-${key}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

function contentState(items: ProgressItem[], stage: StageStatus | undefined, stale: boolean): StepState {
  if (stage?.status === "queued" || stage?.status === "running") return "running";
  if (stale) return "stale";
  const n = done(items);
  if (n === items.length) return "done";
  if (n > 0) return "partial";
  return stage?.status === "failed" || stage?.status === "blocked" ? "problem" : "empty";
}

function buildState(stage: StageStatus | undefined, locked: boolean, stale: boolean): StepState {
  if (locked) return "locked";
  if (stage?.status === "queued" || stage?.status === "running") return "running";
  if (stale) return "stale";
  if (DONE.has(stage?.status ?? "")) return "done";
  if (stage?.status === "failed" || stage?.status === "blocked") return "problem";
  return "empty";
}

function StepHeader({ title, purpose, children }: { title: string; purpose: string; children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 className="font-heading text-2xl font-bold text-ink">{title}</h2>
          <p className="max-w-2xl text-sm leading-relaxed text-ink-2">{purpose}</p>
        </div>
        {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
      </div>
    </header>
  );
}

export default function AuthorWorkspace({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const revealKey = `author:reveal:${projectId}`;
  const stepKey = `author:step:${projectId}`;
  // Спойлеры закрыты по умолчанию; выбор автора запоминается только в этом браузере.
  const [revealed, setRevealed] = useState(() => remembered(revealKey, "0") === "1");
  const [step, setStep] = useState(() => remembered(stepKey, "lore"));
  const [location, setLocation] = useState<string | null>(null);
  const [proposal, setProposal] = useState<EditProposal | null>(null);
  const [affected, setAffected] = useState<string[]>([]);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [publishIssues, setPublishIssues] = useState<ValidationIssue[] | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [plotErrors, setPlotErrors] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [rebuilding, setRebuilding] = useState<string | null>(null); // место, чью карту пересобирают
  const [mapView, setMapView] = useState<"world" | "places">("world");

  useEffect(() => remember(stepKey, step), [step, stepKey]);

  const running = (v?: PreparationView) => (v?.stages ?? []).some((s) => s.status === "queued" || s.status === "running");
  const summary = useQuery({
    queryKey: authorKeys.project(projectId, "summary"),
    queryFn: () => authoring.getProject(projectId, "summary"),
    refetchInterval: (q) => (running(q.state.data?.preparation) ? 3000 : false),
  });
  const full = useQuery({
    queryKey: authorKeys.project(projectId, "full"),
    queryFn: () => authoring.getProject(projectId, "full"),
    enabled: revealed,
    refetchInterval: () => (running(summary.data?.preparation) ? 3000 : false),
  });
  const loreTask = useQuery({
    queryKey: ["author", projectId, "task", "lore"],
    queryFn: () => authoring.task(projectId, "lore"),
    enabled: revealed && step === "lore",
    retry: false,
  });
  const plotTask = useQuery({
    queryKey: ["author", projectId, "task", "plot"],
    queryFn: () => authoring.task(projectId, "plot"),
    enabled: revealed && step === "plot",
    retry: false,
  });
  const map = useQuery({
    queryKey: authorKeys.map(projectId, location ?? ""),
    queryFn: () => authoring.getMap(projectId, location as string),
    enabled: revealed && !!location,
  });

  const mapsStatus = summary.data?.preparation.stages?.find((x) => x.stage === "maps")?.status;
  const [lastMapsStatus, setLastMapsStatus] = useState<string | undefined>(undefined);
  useEffect(() => {
    // пересборка закончилась — показываем новую карту без перезагрузки страницы
    if ((lastMapsStatus === "queued" || lastMapsStatus === "running") && mapsStatus && mapsStatus !== lastMapsStatus) {
      void client.invalidateQueries({ queryKey: ["author", projectId, "map"] });
      void client.invalidateQueries({ queryKey: ["author", projectId, "overview"] });
      void client.invalidateQueries({ queryKey: authorKeys.project(projectId, "full") });
      setMessage(mapsStatus === "ready" ? (rebuilding ? "Карта пересобрана." : "Карты пересобраны.") : `Пересборка не удалась (${mapsStatus}). Прежние карты на месте.`);
      setRebuilding(null);
    }
    setLastMapsStatus(mapsStatus);
  }, [mapsStatus, lastMapsStatus, client, projectId, rebuilding]);

  useEffect(() => {
    // на шаге «Карты» сразу открывается карта первого места
    const locations = (full.data?.preparation.content as { plot?: Plot } | null | undefined)?.plot?.locations;
    if (step === "maps" && !location && locations?.length) setLocation(locations[0].id);
  }, [step, location, full.data]);

  const overview = useQuery({
    queryKey: ["author", projectId, "overview"],
    queryFn: () => authoring.overview(projectId),
    enabled: revealed && step === "maps",
  });

  const refresh = () => client.invalidateQueries({ queryKey: ["author", projectId] });
  const revision = summary.data?.project.draft_revision ?? 0;
  const fail = (e: unknown) => setMessage(e instanceof ApiError ? e.message : "не удалось выполнить действие");

  const prepare = useMutation({
    mutationFn: (v: { stage: string; regenerate: boolean; target?: string }) =>
      authoring.prepare(projectId, {
        stage: v.stage,
        target_ref: v.target ?? null,
        expected_revision: revision,
        request_key: newRequestKey(),
        regenerate: v.regenerate,
      }),
    onSuccess: (receipt) => {
      setMessage(receipt.status === "ready" ? "Этап уже готов с теми же входными данными — результат не изменился." : "Этап поставлен в очередь.");
      void refresh();
    },
    onError: fail,
  });
  const edit = useMutation({
    mutationFn: (patch: DraftPatch) => authoring.applyEdits(projectId, { patch, expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: (r) => {
      setAffected((r.affected ?? []).map((a) => `${a.kind}:${a.ref}`));
      setProposal(null);
      setMessage("Сохранено.");
      void refresh();
    },
    onError: fail,
  });
  const accept = useMutation({
    mutationFn: (ref: string) => authoring.acceptStale(projectId, { refs: [ref], expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: refresh,
    onError: fail,
  });
  const propose = useMutation({
    mutationFn: (instruction: string) => authoring.previewEdit(projectId, { instruction, base_revision: revision }),
    onSuccess: setProposal,
    onError: fail,
  });
  const validate = useMutation({
    mutationFn: () => authoring.validate(projectId, revealed ? "full" : "summary"),
    onSuccess: (r) => {
      setReport(r);
      setPublishIssues(null);
      setPublishError(null);
      void refresh();
    },
    onError: fail,
  });
  const publish = useMutation({
    mutationFn: () => authoring.publish(projectId, { expected_revision: revision, request_key: newRequestKey() }),
    onSuccess: (v) => {
      setPublishError(null);
      setPublishIssues(null);
      setMessage(`Опубликована версия ${v.version}.`);
    },
    onError: (e) => {
      setPublishError(e instanceof ApiError ? e.message : "ошибка публикации");
      const data = e instanceof ApiError ? (e.data as { issues?: ValidationIssue[] } | undefined) : undefined;
      setPublishIssues(data?.issues ?? null);
    },
  });

  if (summary.isLoading) return <p className="p-8 text-center text-muted">Загрузка проекта…</p>;
  if (summary.error || !summary.data) return <p className="p-8 text-center text-bad" role="alert">Проект недоступен.</p>;
  const { project, preparation } = summary.data;
  const content = (full.data?.preparation.content ?? null) as (DraftContent & { plot?: Plot }) | null;
  const lore = (content?.setting?.lore ?? {}) as Lore;
  const plot = (content?.plot ?? {}) as Plot;
  const stale = new Set(preparation.stale ?? []);
  const stageOf = (name: string) => (preparation.stages ?? []).find((s) => s.stage === name);
  const isDone = (name: string) => DONE.has(stageOf(name)?.status ?? "");
  const busy = prepare.isPending || edit.isPending || accept.isPending || propose.isPending || validate.isPending || publish.isPending;
  const worldBuilt = isDone("materialize");
  const mapStale = [...stale].filter((r) => !r.startsWith("stage:"));
  const mapsRunning = ["queued", "running"].includes(stageOf("maps")?.status ?? "");

  const loreItems = loreProgress(lore);
  const plotItems = plotProgress(plot);
  const plotReady = isDone("plot") || (plot.locations ?? []).length > 0;
  const statusLabel = (name: string) => STAGE_STATE_LABELS[stageOf(name)?.status ?? "not_requested"];

  const steps: StepInfo[] = [
    {
      id: "lore",
      title: "Лор мира",
      state: revealed ? contentState(loreItems, stageOf("lore"), stale.has("stage:lore")) : isDone("lore") ? "done" : "empty",
      note: revealed ? `${done(loreItems)} из ${loreItems.length} разделов` : statusLabel("lore"),
    },
    {
      id: "plot",
      title: "Сюжет и NPC",
      state: revealed ? contentState(plotItems, stageOf("plot"), stale.has("stage:plot")) : plotReady ? "done" : "empty",
      note: revealed ? `${done(plotItems)} из ${plotItems.length} частей` : statusLabel("plot"),
    },
    ...(
      [
        ["geography", "География", plotReady],
        ["materialize", "Места, NPC и предметы", isDone("geography")],
        ["maps", "Карты", isDone("materialize")],
      ] as [string, string, boolean][]
    ).map(([id, title, open]) => {
      const mapsCurrent = id === "maps" && open && mapStale.length === 0 && !stale.has("stage:maps") && (stageOf(id)?.status ?? "not_requested") === "not_requested";
      const state = mapsCurrent ? "done" : buildState(stageOf(id), !open, stale.has(`stage:${id}`) || (id === "maps" && mapStale.length > 0));
      const note = mapsCurrent ? "все карты актуальны" : state === "locked" ? "после предыдущего шага" : state === "stale" ? "устарело" : statusLabel(id);
      return { id, title, state, note };
    }),
    {
      id: "review",
      title: "Проверка и публикация",
      state: report ? ((report.errors ?? []).length ? "problem" : "done") : "empty",
      note: report ? `ошибок: ${(report.errors ?? []).length}` : "не проверено",
    },
  ];

  const stageActions = (name: string, paid: boolean) => {
    const st = stageOf(name);
    const status = st?.status ?? "not_requested";
    const active = status === "queued" || status === "running";
    const isStale = stale.has(`stage:${name}`);
    const run = (regenerate: boolean) => {
      if (name === "plot" && worldBuilt && !window.confirm("Новый сюжет удалит уже созданные места, NPC и карты. Продолжить?")) return;
      prepare.mutate({ stage: name, regenerate });
    };
    const failed = status === "failed" || status === "blocked";
    const first = name === "geography" ? "Проверить и сохранить географию" : name === "materialize" ? "Создать места, NPC и предметы" : name === "maps" ? "Пересобрать карты" : "Запустить";
    const verb = status === "not_requested" ? (paid ? "Сгенерировать моделью" : first) : failed || isStale ? "Повторить" : paid ? "Новый вариант" : "Запустить снова";
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-medium ${failed ? "text-bad" : "text-muted"}`} role="status">
          {active ? "выполняется…" : isStale ? "устарело" : STAGE_STATE_LABELS[status]}
          {st?.error_code ? `, код ${st.error_code}` : ""}
        </span>
        <button
          className={`btn min-h-11 px-4 text-sm font-medium ${!paid && status === "not_requested" ? "btn-primary" : ""}`}
          type="button"
          disabled={busy || active}
          onClick={() => run(status !== "not_requested")}
        >
          {verb}
          {paid ? " (платно)" : ""}
        </button>
        {isStale && (
          <button className="btn min-h-11 px-3 text-sm" type="button" disabled={busy} onClick={() => accept.mutate(`stage:${name}`)}>
            Оставить как есть
          </button>
        )}
      </div>
    );
  };

  const reveal = (value: boolean) => {
    setRevealed(value);
    remember(revealKey, value ? "1" : "0");
  };

  const hidden = (
    <div className="flex flex-col items-start gap-4 rounded-2xl border border-line bg-surface p-6 shadow-sm">
      <div className="flex flex-col gap-1.5">
        <h3 className="font-heading text-lg font-semibold text-ink">Режим защиты от спойлеров</h3>
        <p className="max-w-xl text-sm leading-relaxed text-ink-2">
          Содержимое скрыто, чтобы случайно не увидеть тайны мира. Для заполнения его нужно открыть.
        </p>
      </div>
      <button className="btn btn-primary min-h-11 px-5 text-sm font-medium" type="button" onClick={() => reveal(true)}>
        Показать содержимое
      </button>
    </div>
  );

  const pasteLore = async (value: Record<string, unknown>) => {
    const fields = Object.fromEntries(Object.entries(value).filter(([k]) => LORE_KEYS.includes(k)));
    if (!Object.keys(fields).length) {
      setMessage("В JSON нет ни одного раздела лора.");
      return false;
    }
    try {
      await edit.mutateAsync({ operations: [{ op: "set_lore", fields: fields as never }] });
      return true;
    } catch {
      return false;
    }
  };

  const pastePlot = async (value: Record<string, unknown>) => {
    if (worldBuilt && !window.confirm("Новый каркас удалит уже созданные места, NPC и карты. Продолжить?")) return false;
    try {
      const r = await authoring.importPlot(projectId, { plan: value, expected_revision: revision, request_key: newRequestKey() });
      setPlotErrors([]);
      setMessage(r.cleared_entities ? `Каркас принят; прежние места и карты (${r.cleared_entities}) удалены. Проверяю географию…` : "Каркас принят сервером. Проверяю географию…");
      try {
        const fresh = await authoring.getProject(projectId, "summary");
        await authoring.prepare(projectId, { stage: "geography", expected_revision: fresh.project.draft_revision, request_key: newRequestKey(), regenerate: isDone("geography") });
      } catch {
        /* не вышло — шаг «География» запускается кнопкой */
      }
      void refresh();
      return true;
    } catch (e) {
      const data = e instanceof ApiError ? (e.data as { errors?: string[] } | undefined) : undefined;
      setPlotErrors(data?.errors ?? [e instanceof ApiError ? e.message : "импорт не удался"]);
      return false;
    }
  };

  const changedTexts = Object.fromEntries(Object.entries(texts).filter(([k, v]) => v !== String(plot[k] ?? "")));

  const NextStepFooter = ({ nextId, nextTitle }: { nextId: string; nextTitle: string }) => (
    <div className="mt-4 flex items-center justify-between border-t border-line-soft pt-4">
      <span className="text-xs text-muted">Завершили работу над этим этапом?</span>
      <button
        className="btn btn-primary min-h-11 px-4 text-sm font-medium"
        type="button"
        onClick={() => setStep(nextId)}
      >
        Перейти к шагу «{nextTitle}» →
      </button>
    </div>
  );

  let body: ReactNode;
  if (step === "lore") {
    body = (
      <>
        <StepHeader title="Лор мира" purpose="Основа, на которой строится сюжет: обзор, эпоха, области, история, фракции, фигуры и тайны. Вставьте JSON из внешней модели, допишите вручную или сгенерируйте.">
          {stageActions("lore", true)}
        </StepHeader>
        {!revealed ? hidden : (
          <>
            <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-4 sm:p-5 shadow-sm">
              <div className="flex items-center justify-between border-b border-line-soft pb-2.5">
                <span className="font-heading text-sm font-semibold text-ink">Внешняя модель или импорт</span>
                <span className="text-xs text-muted">Задание и вставка JSON</span>
              </div>
              <TaskBox load={() => authoring.task(projectId, "lore")} />
              <JsonPaste
                label="Вставить лор (JSON)"
                schema={loreTask.data?.schema ?? null}
                partial
                busy={busy}
                applyLabel="Добавить в лор"
                preview={(v) => loreProgress({ ...lore, ...Object.fromEntries(Object.entries(v).filter(([k]) => LORE_KEYS.includes(k))) })}
                onApply={pasteLore}
              />
            </div>
            <Checklist title="Что заполнено в лоре" items={loreItems} onJump={(k) => jump("lore", k)} />
            <LoreEditor lore={lore} busy={busy} onSave={(fields) => edit.mutate({ operations: [{ op: "set_lore", fields: fields as never }] })} />
            <NextStepFooter nextId="plot" nextTitle="Сюжет и NPC" />
          </>
        )}
      </>
    );
  } else if (step === "plot") {
    body = (
      <>
        <StepHeader title="Сюжет и NPC" purpose="Каркас приключения: завязка, антагонисты, места, NPC, акты, тайны и финалы. Вставленный каркас сервер проверяет так же строго, как ответ встроенной модели.">
          {stageActions("plot", true)}
        </StepHeader>
        {!revealed ? hidden : (
          <>
            <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-4 sm:p-5 shadow-sm">
              <div className="flex items-center justify-between border-b border-line-soft pb-2.5">
                <span className="font-heading text-sm font-semibold text-ink">Внешняя модель или импорт</span>
                <span className="text-xs text-muted">Задание и вставка каркаса сюжета</span>
              </div>
              <TaskBox load={() => authoring.task(projectId, "plot")} />
              {plotTask.error && (
                <p className="text-sm text-warn">Схема сюжета недоступна ({plotTask.error instanceof ApiError ? plotTask.error.message : "ошибка"}); вставку всё равно проверит сервер.</p>
              )}
              <JsonPaste
                label="Вставить каркас сюжета (JSON)"
                schema={plotTask.data?.schema ?? null}
                busy={busy}
                applyLabel="Проверить и принять каркас"
                serverErrors={plotErrors}
                preview={(v) => plotProgress(v)}
                onApply={pastePlot}
              />
            </div>
            <Checklist title="Что заполнено в сюжете" items={plotItems} onJump={(k) => jump("plot", k)} />
            <fieldset className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-4 sm:p-5 shadow-sm">
              <div className="flex items-center justify-between border-b border-line-soft pb-2">
                <legend className="font-heading text-base font-semibold text-ink">Тексты сюжета</legend>
                <span className="text-xs text-muted">Основные описания для мастера и игроков</span>
              </div>
              {PLOT_TEXT.map(([key, label]) => (
                <label key={key} id={`plot-${key}`} className="flex scroll-mt-24 flex-col gap-1.5 text-sm">
                  <span className="font-medium text-ink">{label}</span>
                  <textarea
                    className="min-h-20 rounded-xl border border-line bg-raised p-3 text-sm text-ink transition-colors focus:border-accent focus:outline-none"
                    value={texts[key] ?? String(plot[key] ?? "")}
                    onChange={(e) => setTexts({ ...texts, [key]: e.target.value })}
                  />
                </label>
              ))}
              <button
                className="btn btn-primary min-h-11 self-start px-4 text-sm font-medium"
                type="button"
                disabled={busy || !Object.keys(changedTexts).length}
                onClick={() => {
                  edit.mutate({ operations: [{ op: "set_plot_text", fields: changedTexts }] });
                  setTexts({});
                }}
              >
                Сохранить тексты
              </button>
            </fieldset>
            <div id="plot-locations" className="scroll-mt-24">
              <ContentEditor
                content={content ?? {}}
                busy={busy}
                proposal={proposal}
                affected={affected}
                onRename={(ref, name) => edit.mutate({ operations: [{ op: "update_plot_object", ref, fields: { name } }] })}
                onPropose={(text) => propose.mutate(text)}
                onApplyProposal={() => proposal && edit.mutate(proposal.patch)}
                onDismissProposal={() => setProposal(null)}
              />
            </div>
            <NextStepFooter nextId="geography" nextTitle="География" />
          </>
        )}
      </>
    );
  } else if (step === "geography" || step === "materialize" || step === "maps") {
    const info: Record<string, [string, string]> = {
      geography: [
        "География",
        "Ниже — регионы, места и маршруты так, как они записаны в каркасе. Кнопка проверяет их (существуют ли места и части, нет ли петель в регионах и дублей маршрутов) и сохраняет как основу для карт. Бесплатно, без модели.",
      ],
      materialize: ["Места, NPC и предметы", "Создаются все места каркаса с картами участков, жители в своих домах, ключевые предметы и зацепки."],
      maps: ["Карты", "Пересобирает карты мест, которые вы изменили: новая карта заменяет старую только целиком готовой."],
    };
    const locked = steps.find((s) => s.id === step)?.state === "locked";
    const status = stageOf(step)?.status ?? "not_requested";
    const upstream: Record<string, [string, string]> = {
      geography: ["plot", "Сюжет и NPC"],
      materialize: ["geography", "География"],
      maps: ["materialize", "Места, NPC и предметы"],
    };
    const [needId, needTitle] = upstream[step];
    const geographyChecked = isDone("geography");
    body = (
      <>
        <StepHeader title={info[step][0]} purpose={info[step][1]} />
        {locked ? (
          <div className="flex flex-col items-start gap-4 rounded-2xl border border-line bg-surface p-6 shadow-sm" role="status">
            <p className="text-sm text-ink-2">Этот шаг откроется, когда будет выполнен шаг «{needTitle}».</p>
            <button className="btn btn-primary min-h-11 px-4 text-sm font-medium" type="button" onClick={() => setStep(needId)}>
              Перейти к шагу «{needTitle}»
            </button>
          </div>
        ) : step === "maps" && isDone("materialize") ? (
          <div className="flex flex-col items-start gap-3 rounded-2xl border-2 border-accent/60 bg-surface p-5 shadow-sm">
            <p className="text-sm leading-relaxed text-ink-2">
              {mapsRunning
                ? "Карты пересобираются. Когда закончится, карта ниже обновится сама."
                : "Карты созданы на предыдущем шаге. Пересоберите их, чтобы получить новые планировки — например, после исправления генератора. Прежняя карта остаётся, пока новая не готова целиком."}
            </p>
            {stageOf("maps")?.error_code && !mapsRunning && <p className="text-sm text-bad">Прошлая пересборка не удалась: {stageOf("maps")?.error_code}</p>}
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                className="btn btn-primary min-h-11 px-5 text-sm font-medium"
                type="button"
                disabled={busy || mapsRunning}
                onClick={() => {
                  if (window.confirm("Пересобрать карты всех мест? Планировка каждого места — вызов модели.")) {
                    prepare.mutate({ stage: "maps", regenerate: true, target: "*" });
                  }
                }}
              >
                {mapsRunning ? "Пересобираю карты…" : "Пересобрать карты"}
              </button>
              <button className="btn min-h-11 px-4 text-sm" type="button" onClick={() => setStep("review")}>
                Перейти к проверке
              </button>
            </div>
          </div>
        ) : status === "not_requested" ? (
          <div className="flex flex-col gap-3 rounded-2xl border-2 border-accent/60 bg-surface p-5 shadow-sm">
            <p className="text-sm leading-relaxed text-ink-2">Шаг ещё не выполнен. Он бесплатный и занимает несколько секунд: нажмите кнопку, и откроется следующий шаг.</p>
            {stageActions(step, false)}
          </div>
        ) : (
          stageActions(step, false)
        )}
        {!locked && step === "maps" && isDone("materialize") && (revealed ? (
          <section aria-label="Карты мест" className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="Вид">
              {([["world", "Схема мира"], ["places", "Карты мест"]] as const).map(([id, label]) => (
                <button
                  key={id}
                  role="tab"
                  type="button"
                  aria-selected={mapView === id}
                  className={`btn min-h-11 px-5 text-sm font-medium ${mapView === id ? "btn-primary shadow-sm" : ""}`}
                  onClick={() => setMapView(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {mapView === "world" ? (
              overview.data ? <WorldOverview overview={overview.data} /> : <p className="text-sm text-muted">Загрузка схемы…</p>
            ) : (
            <div className="flex flex-col gap-4">
              <h3 className="font-heading text-base font-semibold text-ink">Карты мест</h3>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Места">
                {(plot.locations ?? []).map((loc) => (
                  <button
                    key={loc.id}
                    type="button"
                    className={`btn min-h-11 px-4 text-sm font-medium ${(location ?? plot.locations?.[0]?.id) === loc.id ? "btn-primary shadow-sm" : ""}`}
                    aria-pressed={(location ?? plot.locations?.[0]?.id) === loc.id}
                    onClick={() => setLocation(loc.id)}
                  >
                    {loc.name}
                  </button>
                ))}
              </div>
              {map.isLoading && <p className="text-sm text-muted">Загрузка карты…</p>}
              {map.data && (
                <MapPreview
                  key={map.data.location_ref}
                  map={map.data}
                  rebuild={{
                    disabled: busy || mapsRunning,
                    running: mapsRunning && rebuilding === map.data.location_ref,
                    onRebuild: () => {
                      const ref = map.data!.location_ref;
                      setRebuilding(ref);
                      prepare.mutate({ stage: "maps", regenerate: true, target: ref });
                    },
                  }}
                />
              )}
              <p className="text-xs text-muted">Прежняя карта остаётся, пока новая не будет полностью готова.</p>
            </div>
            )}
          </section>
        ) : hidden)}
        {!locked && revealed && step !== "maps" && (plot.locations ?? []).length > 0 && (
          <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 shadow-sm">
            <h3 className="font-heading text-base font-semibold text-ink">
              {step === "geography" && !geographyChecked ? "Как записано в каркасе (ещё не проверено)" : "Места и маршруты"}
            </h3>
            <GeographyView regions={plot.regions ?? []} locations={plot.locations ?? []} routes={plot.routes ?? []} selected={location} onSelect={setLocation} />
            {location && map.data && <MapPreview map={map.data} />}
          </div>
        )}
        {step === "maps" && mapStale.length > 0 && (
          <ul className="flex flex-col gap-1.5 rounded-2xl border border-warn/40 bg-warn/10 p-4 text-sm" aria-label="Устаревшие карты">
            {mapStale.map((ref) => (
              <li key={ref} className="flex items-center justify-between gap-3 rounded-lg border border-line-soft bg-surface/70 p-2">
                <code className="text-xs font-mono">{ref}</code>
                <button className="btn min-h-9 px-3 text-xs" type="button" disabled={busy} onClick={() => accept.mutate(ref)}>Принять как есть</button>
              </li>
            ))}
          </ul>
        )}
        {!locked && step === "geography" && isDone("geography") && (
          <NextStepFooter nextId="materialize" nextTitle="Места, NPC и предметы" />
        )}
        {!locked && step === "materialize" && isDone("materialize") && (
          <NextStepFooter nextId="maps" nextTitle="Карты" />
        )}
      </>
    );
  } else {
    body = (
      <>
        <StepHeader title="Проверка и публикация" purpose="Проверка находит всё, что не готово: пустые карты, недостижимые места, предметы только в тексте, устаревшие результаты. Опубликовать можно только без ошибок." />
        <ValidationPanel report={report} publishIssues={publishIssues} publishError={publishError} busy={busy} onValidate={() => validate.mutate()} onPublish={() => publish.mutate()} />
      </>
    );
  }

  const spent = preparation.spent_usd ?? 0;
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-4 sm:p-6">
      {/* Top Project HUD */}
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-heading text-2xl font-bold tracking-tight text-ink">{project.title}</h1>
          <span className="rounded-full bg-line-soft px-2.5 py-0.5 text-xs font-medium text-muted">
            ревизия {project.draft_revision}
          </span>
          <span className="rounded-full border border-line-soft bg-raised px-2.5 py-0.5 text-xs text-muted">
            потрачено ${spent.toFixed(4)}
            {preparation.budget_usd != null ? ` из $${preparation.budget_usd.toFixed(2)}` : ""}
          </span>
        </div>
        <button
          className="btn min-h-10 px-3.5 text-xs font-medium"
          type="button"
          aria-pressed={revealed}
          onClick={() => reveal(!revealed)}
        >
          {revealed ? "Скрыть содержимое" : "Показать содержимое"}
        </button>
      </header>

      {message && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-line bg-raised p-3.5 text-sm shadow-sm" role="status">
          <span className="text-ink">{message}</span>
          <button className="btn min-h-8 px-2.5 text-xs" type="button" onClick={() => setMessage(null)}>Скрыть</button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <StepNav steps={steps} active={step} onSelect={setStep} />
        <main className="flex min-w-0 flex-col gap-5">{body}</main>
      </div>
    </div>
  );
}
