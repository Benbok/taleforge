import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { authoring, authorKeys, mergeDraft, newRequestKey, type StudioFields, type StudioView } from "../lib/authoring";

interface FieldMeta {
  key: keyof StudioFields;
  label: string;
  hint: string;
  tip?: string;
  placeholder?: string;
  rows?: number;
  badge?: string;
}

const SECTION_1: FieldMeta[] = [
  {
    key: "premise",
    label: "Замысел",
    hint: "О чём приключение и что интересно исследовать.",
    tip: "Сформулируйте суть в 1–2 предложениях: главная тайна, центральный конфликт и цель отряда.",
    placeholder: "Например: Исследование затонувшего города до того, как его поглотит разлом…",
    rows: 3,
    badge: "Обязательно",
  },
];

const SECTION_2: FieldMeta[] = [
  {
    key: "laws",
    label: "Законы мира",
    hint: "Что возможно и невозможно. Мастер задаёт вопросы, а изменения сохраняете вы.",
    tip: "Зафиксируйте правила реальности: действует ли магия, можно ли воскрешать мёртвых, есть ли технологии. Мастер не сможет нарушить эти законы.",
    placeholder: "Что возможно: …\nЧто невозможно: …",
    rows: 4,
    badge: "Фундамент",
  },
  {
    key: "world",
    label: "Мир",
    hint: "Места, эпоха и повседневная жизнь.",
    tip: "Опишите географию, климат, быт жителей и уровень цивилизации.",
    placeholder: "Архипелаг летающих островов, вечный туман, паровые дирижабли и кристальные маяки…",
    rows: 4,
  },
];

const SECTION_3: FieldMeta[] = [
  {
    key: "inhabitants",
    label: "Обитатели",
    hint: "Народы, существа и общества.",
    tip: "Кто населяет мир: разумные виды, доминирующие фракции и стартовый масштаб героев.",
    placeholder: "Люди побережья, глубинные ныряльщики, духи глубин…",
    rows: 3,
  },
  {
    key: "powers",
    label: "Силы и возможности",
    hint: "Как действуют магия, технологии и другие силы.",
    tip: "Источники чудес и приёмов: внутренняя энергия, древние артефакты, молитвы или импланты.",
    placeholder: "Магия формул, резонанс кристаллов, цена применения — перегрузка разума…",
    rows: 3,
  },
];

const SECTION_4: FieldMeta[] = [
  {
    key: "start",
    label: "Начало приключения",
    hint: "Конкретное место и ситуация первого игрового шага. Приветствие и связки героев с ней мастер придумает сам при старте игры.",
    tip: "Где именно герои делают первый вдох и с какой непосредственной дилеммой сталкиваются.",
    placeholder: "Таверна у маяка в разгар шторма; в дверь стучится раненый гонец…",
    rows: 3,
  },
  {
    key: "history",
    label: "История",
    hint: "Прошлое мира; сведения доступны автору и мастеру.",
    tip: "Недавняя война, падение империи или надвигающееся затмение.",
    placeholder: "Сто лет назад произошёл Раскол; древние знания были утрачены…",
    rows: 3,
  },
  {
    key: "style",
    label: "Стиль",
    hint: "Тон и желаемое впечатление.",
    tip: "Атмосфера повествования: мрачное выживание, таинственный детектив или героический эпос.",
    placeholder: "Таинственный, меланхоличный, с акцентом на открытия и находчивость…",
    rows: 2,
  },
];

const SECTION_5: FieldMeta[] = [
  {
    key: "public_text",
    label: "Текст для игроков",
    hint: "Только этот текст и название войдут в открытое описание версии.",
    tip: "Открытая вводная карточка, которую увидят игроки при выборе этого мира или входе за стол.",
    placeholder: "Краткий синопсис мира для буклета кампании…",
    rows: 3,
  },
  {
    key: "secret_text",
    label: "Секреты мастера",
    hint: "Скрытые мотивы, тайны и будущие открытия.",
    tip: "Истинные намерения ключевых NPC, запретные тайны и скрытые угрозы. Игроки никогда не увидят этот блок.",
    placeholder: "Главный хранитель на самом деле запечатал в подземелье собственного близнеца…",
    rows: 3,
    badge: "Только для мастера",
  },
];

const ALL_META = [...SECTION_1, ...SECTION_2, ...SECTION_3, ...SECTION_4, ...SECTION_5];
const metaOf = (key: keyof StudioFields) => ALL_META.find((m) => m.key === key)!;
// The master's review asks for these four, so they stay in the open part of the form.
const MAIN_KEYS: (keyof StudioFields)[] = ["laws", "world", "start"];
const EXTRA_KEYS: (keyof StudioFields)[] = ["inhabitants", "powers", "history", "style", "public_text", "secret_text"];

export default function UniversalWorldStudio({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const key = ["author", projectId, "studio"];
  const studio = useQuery({ queryKey: key, queryFn: () => authoring.getStudio(projectId) });
  const project = useQuery({
    queryKey: authorKeys.project(projectId, "summary"),
    queryFn: () => authoring.getProject(projectId, "summary"),
  });
  const [fields, setFields] = useState<StudioFields | null>(null);
  const [answer, setAnswer] = useState("");
  // The idea typed on the project list survives a failed draft, so the author can retry here.
  const [idea, setIdea] = useState(() => (useLocation().state as { idea?: string } | null)?.idea ?? "");
  const acceptKey = useRef(newRequestKey());
  const launchKeys = useRef<Record<string, string>>({});

  useEffect(() => {
    if (studio.data) {
      setFields(studio.data.fields);
      acceptKey.current = newRequestKey();
    }
  }, [studio.data?.draft_revision]);

  const refresh = () => {
    void client.invalidateQueries({ queryKey: authorKeys.projects });
    void client.invalidateQueries({ queryKey: authorKeys.project(projectId, "summary") });
    void client.invalidateQueries({ queryKey: authorKeys.library });
  };

  const save = useMutation({
    mutationFn: () => authoring.saveStudio(projectId, studio.data!.draft_revision, fields!),
    onSuccess: (view) => {
      client.setQueryData(key, view);
      refresh();
    },
  });

  const review = useMutation({
    mutationFn: (text: string) => authoring.reviewStudio(projectId, studio.data!.draft_revision, text),
    onSuccess: (result) => {
      client.setQueryData<StudioView>(key, (previous) => (previous ? { ...previous, review: result } : previous));
      setAnswer("");
    },
  });

  // A proposal only: it fills the fields the author left empty and saves nothing.
  const draft = useMutation({
    mutationFn: () => authoring.draftStudio(projectId, idea.trim()),
    onSuccess: (proposal) => setFields((old) => (old ? mergeDraft(old, proposal) : old)),
  });

  const accept = useMutation({
    mutationFn: () => authoring.acceptStudio(projectId, studio.data!.draft_revision, acceptKey.current),
    onSuccess: refresh,
  });

  const launch = useMutation({
    mutationFn: (versionId: string) => {
      launchKeys.current[versionId] ??= newRequestKey();
      return authoring.launch(versionId, {
        request_key: launchKeys.current[versionId],
        options: {
          name: fields!.title,
          owner_plays: true,
          players: 1,
          excluded_themes: fields!.excluded_themes,
        },
      });
    },
    onSuccess: (receipt) => navigate(receipt.url),
  });

  const dirty = !!fields && JSON.stringify(fields) !== JSON.stringify(studio.data?.fields);
  const busy = save.isPending || review.isPending || accept.isPending || launch.isPending || draft.isPending;
  const error = save.error || review.error || accept.error || launch.error || draft.error || studio.error;

  if (!fields) {
    return (
      <main className="workshop-page mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <p className="workshop-notice text-muted" role={studio.error ? "alert" : "status"}>
          {studio.error ? studio.error.message : "Загрузка творческой студии…"}
        </p>
      </main>
    );
  }

  const update = <K extends keyof StudioFields>(name: K, value: StudioFields[K]) =>
    setFields((old) => (old ? { ...old, [name]: value } : old));

  const receipt = studio.data?.review;
  const publishedVersions = project.data?.published ?? [];

  // Подсчёт заполненности для прогресс-бара компаньона
  const allFieldKeys: (keyof StudioFields)[] = [
    "premise",
    "laws",
    "world",
    "inhabitants",
    "powers",
    "start",
    "history",
    "style",
    "public_text",
    "secret_text",
  ];
  const filledCount = allFieldKeys.filter((k) => String(fields[k] ?? "").trim().length > 0).length;
  const percent = Math.min(100, Math.round((filledCount / allFieldKeys.length) * 100));

  const currentStep = publishedVersions.length > 0 && !dirty ? 2 : receipt ? 1 : 0;

  return (
    <main className="workshop-page mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
      {/* Мастхед в едином стиле Мастерской героя */}
      <header className="workshop-masthead relative overflow-hidden rounded-2xl border border-line p-6 md:p-8">
        <div className="workshop-emblem" aria-hidden="true">
          ✧
        </div>
        <nav
          aria-label="Навигация"
          className="relative mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted"
        >
          <Link to="/author" className="text-accent hover:underline flex items-center gap-1 transition-colors">
            ← Проекты
          </Link>
          <span className="text-line" aria-hidden="true">
            /
          </span>
          <span>Творческая студия</span>
        </nav>

        <div className="relative flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="font-heading text-3xl tracking-tight md:text-4xl text-ink">Творческая студия</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
              Опишите мир, обсудите вопросы с мастером и примите версию для независимых приключений.
            </p>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3.5 py-1.5 rounded-full border border-line bg-surface text-ink-2 shadow-sm">
            <span className={`inline-block h-2 w-2 rounded-full ${dirty ? "bg-warn animate-pulse" : "bg-patina"}`} />
            <span>Редакция {studio.data?.draft_revision}</span>
            <span className="text-muted">·</span>
            <span className={dirty ? "text-warn font-semibold" : "text-patina-hi font-semibold"}>
              {dirty ? "есть несохранённые изменения" : "сохранена"}
            </span>
          </div>
        </div>

        {/* Этапы подготовки мира */}
        <ol className="relative mt-7 flex gap-2 sm:gap-5" aria-label="Этапы подготовки мира">
          {[
            { label: "Замысел и законы", idx: 0 },
            { label: "Беседа с мастером", idx: 1 },
            { label: "Принятые версии", idx: 2 },
          ].map(({ label, idx }) => {
            const isDone = (idx === 0 && !dirty && !!fields.title.trim()) || (idx === 1 && receipt?.status === "ready");
            const isCurrent = idx === currentStep;
            return (
              <li
                key={label}
                aria-current={isCurrent ? "step" : undefined}
                className={`workshop-step ${isCurrent ? "is-current" : ""} ${isDone ? "is-done" : ""}`}
              >
                <span className="workshop-step-number" aria-hidden="true">
                  {isDone ? "✓" : `0${idx + 1}`}
                </span>
                <span>{label}</span>
              </li>
            );
          })}
        </ol>
      </header>

      {error && (
        <p role="alert" className="workshop-notice border-bad text-bad">
          {error instanceof ApiError ? error.message : "Не удалось выполнить действие. Повторите попытку."}
        </p>
      )}

      {/* Основная рабочая сетка: слева карточки формы, справа студийный компаньон */}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="flex min-w-0 flex-col gap-6">
          <form
            className="flex flex-col gap-6"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            {/* Карточка 01: Название и Замысел */}
            <section className="card flex flex-col gap-5 p-5 md:p-6 shadow-sm">
              <div className="border-b border-line pb-4">
                <span className="text-xs uppercase tracking-widest text-patina font-semibold">01 / Основа</span>
                <h2 className="mt-1 font-heading text-xl font-bold text-ink">Название и замысел</h2>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  Задайте название и короткую суть, вокруг которой строится приключение.
                </p>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="studio-title" className="text-sm font-semibold text-ink">
                    Название мира <span className="text-accent">*</span>
                  </label>
                  <span className="rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
                    Обязательно
                  </span>
                </div>
                <input
                  id="studio-title"
                  className="field workshop-field font-medium"
                  maxLength={128}
                  required
                  placeholder="Например: Пепельные Архипелаги или Корпорация «Зенит»"
                  value={fields.title}
                  onChange={(e) => update("title", e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-2 rounded-xl border border-accent/30 bg-surface-2/30 p-4">
                <label htmlFor="studio-idea" className="text-sm font-semibold text-ink">
                  Есть готовая идея?
                </label>
                <p className="text-xs leading-relaxed text-muted">
                  Назовите вселенную или опишите мир в нескольких фразах. Мастер предложит черновик для пустых полей,
                  а ваш текст и сохранённые данные он не тронет.
                </p>
                <textarea
                  id="studio-idea"
                  aria-label="Идея мира"
                  className="field workshop-field min-h-20"
                  maxLength={4000}
                  placeholder="Например: «Властелин колец», 3018 год, Братство выходит из Раздола…"
                  value={idea}
                  onChange={(e) => setIdea(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-outline-copper self-start font-mono text-xs"
                  disabled={busy || !idea.trim()}
                  onClick={() => draft.mutate()}
                >
                  {draft.isPending ? "Мастер пишет черновик…" : "Заполнить из идеи"}
                </button>
              </div>

              {SECTION_1.map((meta) => renderFieldBlock(meta, fields, update))}
            </section>

            {/* Карточка 02: то, без чего мастер не примет мир */}
            <section className="card flex flex-col gap-5 p-5 md:p-6 shadow-sm">
              <div className="border-b border-line pb-4">
                <span className="text-xs uppercase tracking-widest text-patina font-semibold">02 / Мир и законы</span>
                <h2 className="mt-1 font-heading text-xl font-bold text-ink">Законы, мир и начало</h2>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  Фундаментальные правила мира незыблемы: мастер строго следует им и не меняет молча.
                </p>
              </div>

              {MAIN_KEYS.map((k) => renderFieldBlock(metaOf(k), fields, update))}
            </section>

            {/* Дополнительно: открывается сам, если что-то уже заполнено */}
            <details
              data-testid="extra-fields"
              className="card p-5 md:p-6 shadow-sm"
              open={EXTRA_KEYS.some((k) => String(fields[k]).trim()) || undefined}
            >
              <summary className="cursor-pointer font-heading text-xl font-bold text-ink">Дополнительно</summary>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                Необязательно: обитатели, силы, история, тон, текст для игроков и секреты мастера.
              </p>
              <div className="mt-4 flex flex-col gap-5">
                {EXTRA_KEYS.map((k) => renderFieldBlock(metaOf(k), fields, update))}

                <div className="grid gap-4 sm:grid-cols-2 pt-2 border-t border-line">
                  <div className="flex flex-col gap-2">
                    <label htmlFor="studio-difficulty" className="text-sm font-semibold text-ink">
                      Сложность
                    </label>
                    <select
                      id="studio-difficulty"
                      className="field workshop-field"
                      value={fields.difficulty}
                      onChange={(e) => update("difficulty", e.target.value as StudioFields["difficulty"])}
                    >
                      <option value="easy">Лёгкая</option>
                      <option value="normal">Обычная</option>
                      <option value="hard">Трудная</option>
                      <option value="deadly">Смертельная</option>
                    </select>
                  </div>

                  <div className="flex flex-col gap-2">
                    <label htmlFor="studio-taboos" className="text-sm font-semibold text-ink">
                      Исключённые темы
                    </label>
                    <input
                      id="studio-taboos"
                      className="field workshop-field"
                      value={fields.excluded_themes.join(", ")}
                      onChange={(e) =>
                        update(
                          "excluded_themes",
                          e.target.value.split(",").map((x) => x.trim())
                        )
                      }
                      placeholder="Через запятую (например: пауки, насилие)"
                    />
                  </div>
                </div>
              </div>
            </details>

            {/* Панель действий формы */}
            <div className="card flex flex-wrap items-center justify-between gap-4 p-5 shadow-sm">
              <div className="text-xs leading-relaxed text-muted">
                {dirty ? (
                  <span className="text-warn font-medium">Есть несохранённые изменения в полях.</span>
                ) : (
                  <span>Все поля сохранены. Можно переходить к согласованию с мастером ниже.</span>
                )}
              </div>

              <button
                className="btn btn-primary workshop-submit"
                disabled={busy || !dirty || !fields.title.trim()}
                type="submit"
              >
                {save.isPending ? "Сохранение…" : "Сохранить мир"}
              </button>
            </div>
          </form>

          {/* Секция: Обсуждение с мастером */}
          <section
            className="card flex flex-col gap-5 p-5 md:p-7 shadow-sm border border-line"
            aria-label="Проверка мира"
          >
            <div className="border-b border-line pb-4 flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-widest text-patina font-semibold">Шаг 2</p>
                <h2 className="mt-1 font-heading text-xl font-bold text-ink">Обсуждение с мастером</h2>
              </div>
              {receipt?.status === "ready" && (
                <span className="rounded-full bg-patina/15 border border-patina/40 px-3 py-1 font-mono text-xs font-semibold text-patina-hi">
                  ✓ ГОТОВ К ПРИНЯТИЮ
                </span>
              )}
            </div>

            {dirty && (
              <p className="workshop-notice text-warn">
                Сохраните изменения перед проверкой и принятием версии.
              </p>
            )}

            {!receipt && (
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm text-muted">
                  После заполнения сохраните мир и отправьте его на проверку. Мастер проверит непротиворечивость
                  фундаментальных законов и задаст адресные вопросы при необходимости.
                </p>
                <button
                  className="btn btn-outline-copper"
                  disabled={busy || dirty}
                  onClick={() => review.mutate("")}
                >
                  {review.isPending ? "Мастер проверяет мир…" : "Проверить мир с мастером"}
                </button>
              </div>
            )}

            {/* Диалог ревью с мастером */}
            {receipt?.question && (
              <div className="flex flex-col gap-4 border-t border-line pt-4">
                <div className="workshop-message is-master">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-mono text-xs font-bold uppercase tracking-wider text-patina">
                      Вопрос ИИ-мастера
                    </span>
                  </div>
                  <p className="text-sm text-ink leading-relaxed">{receipt.question}</p>
                </div>

                <div className="flex flex-col gap-2">
                  <label htmlFor="studio-answer" className="text-sm font-semibold text-ink">
                    Ответ мастеру
                  </label>
                  <textarea
                    id="studio-answer"
                    aria-label="Ответ мастеру"
                    className="field workshop-field min-h-24"
                    placeholder="Ответьте своими словами, чтобы уточнить замысел мира…"
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                  />
                  <button
                    className="btn btn-primary self-start mt-1 font-mono text-xs"
                    disabled={busy || dirty || !answer.trim()}
                    onClick={() => review.mutate(answer)}
                  >
                    {review.isPending ? "Отправка…" : "Ответить мастеру"}
                  </button>
                </div>
              </div>
            )}

            {receipt?.notes && receipt.notes.length > 0 && (
              <div className="flex flex-col gap-2 border-t border-line pt-4">
                <span className="font-mono text-xs font-semibold text-muted uppercase">Замечания мастера:</span>
                {receipt.notes.map((note, i) => (
                  <p key={i} className="text-xs text-ink-2 leading-relaxed pl-3 border-l-2 border-line">
                    {note}
                  </p>
                ))}
              </div>
            )}

            {receipt?.suggestions && receipt.suggestions.length > 0 && (
              <div className="flex flex-col gap-3 border-t border-line pt-4">
                <span className="font-mono text-xs font-semibold text-muted uppercase">Предложения мастера:</span>
                {receipt.suggestions.map((sug) => {
                  const label = metaOf(sug.field).label;
                  const applied = fields[sug.field] === sug.text;
                  return (
                    <div key={sug.field} className="rounded-xl border border-line bg-surface-2/30 p-3">
                      <p className="text-xs font-semibold text-ink">{label}</p>
                      <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-ink-2">{sug.text}</p>
                      <button
                        type="button"
                        className="btn btn-outline-copper mt-2 font-mono text-xs"
                        aria-label={`Применить предложение: ${label}`}
                        disabled={applied}
                        onClick={() => update(sug.field, sug.text)}
                      >
                        {applied ? "Применено" : "Применить"}
                      </button>
                    </div>
                  );
                })}
                <p className="text-xs text-muted">Применённое попадёт в поля как несохранённая правка: сохраните и проверьте снова.</p>
              </div>
            )}

            {receipt?.status === "ready" && (
              <div className="flex flex-col gap-3 rounded-xl border border-patina/40 bg-patina/10 p-4 mt-2">
                <div className="flex items-center gap-2 text-patina-hi font-semibold text-sm">
                  <span>✓</span>
                  <span>Мастер готов принять эту редакцию.</span>
                </div>
                <p className="text-xs text-muted leading-relaxed">
                  Все фундаментальные законы и стартовые параметры согласованы. Нажмите кнопку ниже, чтобы зафиксировать
                  неизменяемый слепок версии.
                </p>
              </div>
            )}

            <button
              className="btn btn-primary self-start workshop-submit mt-2 font-mono text-xs font-semibold tracking-wider"
              disabled={busy || dirty || receipt?.status !== "ready"}
              onClick={() => accept.mutate()}
            >
              {accept.isPending ? "Фиксация слепка…" : "Принять версию"}
            </button>
          </section>

          {/* Секция: Принятые версии */}
          <section className="card flex flex-col gap-5 p-5 md:p-7 shadow-sm" aria-label="Принятые версии">
            <div className="border-b border-line pb-4 flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-widest text-patina font-semibold">Шаг 3</p>
                <h2 className="mt-1 font-heading text-xl font-bold text-ink">Принятые версии</h2>
              </div>
              <span className="text-xs text-muted">Всего версий: {publishedVersions.length}</span>
            </div>

            {publishedVersions.map((v) => (
              <div
                key={v.id}
                className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface p-5 shadow-sm transition-all hover:border-accent/40"
              >
                <div className="flex items-center gap-3.5">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-patina/20 border border-patina text-patina-hi font-bold text-sm">
                    ✓
                  </span>
                  <div>
                    <span className="font-heading text-base font-bold text-ink">
                      Версия {v.version} · редакция {v.source_revision}
                    </span>
                    <p className="text-xs text-muted mt-0.5">
                      Готова к независимым прохождениям · Изолированное состояние
                    </p>
                  </div>
                </div>

                <button
                  className="btn btn-primary font-mono text-xs tracking-wider px-4 py-2"
                  disabled={busy}
                  onClick={() => launch.mutate(v.id)}
                >
                  {launch.isPending ? "Запуск стола…" : `Запустить версию ${v.version}`}
                </button>
              </div>
            ))}

            {!publishedVersions.length && (
              <p className="text-sm text-muted">
                После принятия здесь появится неизменная версия мира.
              </p>
            )}
          </section>
        </div>

        {/* Правая колонка: Студийный компаньон (Progress Sidebar) */}
        <aside className="workshop-companion card flex flex-col gap-5 p-5 md:p-6" aria-label="Готовность мира">
          <div className="flex items-center gap-4">
            <div
              className="workshop-progress"
              role="progressbar"
              aria-label="Заполненность описания"
              aria-valuenow={percent}
              aria-valuemin={0}
              aria-valuemax={100}
              style={{
                background: `conic-gradient(var(--tf-patina) ${percent}%, var(--tf-border) 0)`,
              }}
            >
              <span>
                {percent}
                <small>%</small>
              </span>
            </div>
            <div>
              <p className="font-heading text-lg font-bold text-ink">Мир обретает форму</p>
              <p className="mt-0.5 text-xs text-muted">
                Заполнено {filledCount} из {allFieldKeys.length} разделов
              </p>
            </div>
          </div>

          <p className="text-xs leading-relaxed text-muted">
            {filledCount >= 2
              ? "Базовая основа готова. Чем точнее описаны фундаментальные законы, тем убедительнее мастер ведёт приключение."
              : "Начните с названия и замысла мира. Остальные законы и детали добавляйте по мере готовности."}
          </p>

          <ul className="space-y-2.5 border-y border-line py-4">
            {allFieldKeys.map((k) => {
              const meta = ALL_META.find((m) => m.key === k);
              const isFilled = String(fields[k] ?? "").trim().length > 0;
              return (
                <li key={k} className={`flex items-center gap-3 text-xs ${isFilled ? "text-ink" : "text-muted"}`}>
                  <span className={`workshop-check ${isFilled ? "is-filled" : ""}`} aria-hidden="true">
                    {isFilled ? "✓" : "·"}
                  </span>
                  <span className="flex-1 truncate">{meta?.label ?? k}</span>
                  <span className="sr-only">{isFilled ? "Заполнено" : "Не заполнено"}</span>
                </li>
              );
            })}
          </ul>

          <div className="flex gap-3">
            <span className="workshop-rule-number" aria-hidden="true">
              ✧
            </span>
            <div>
              <p className="text-xs font-semibold text-ink">Законы мира незыблемы</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted">
                ИИ-мастер строго соблюдает законы реальности и не меняет их молча. Каждая запущенная игра получает
                независимую копию мира.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}

function renderFieldBlock(
  meta: FieldMeta,
  fields: StudioFields,
  update: <K extends keyof StudioFields>(name: K, value: StudioFields[K]) => void
) {
  const isSecret = meta.key === "secret_text";
  const isLaws = meta.key === "laws";

  return (
    <div
      key={meta.key}
      className={`flex flex-col gap-2 ${
        isSecret
          ? "rounded-xl border border-warn/40 bg-warn/5 p-4"
          : isLaws
          ? "rounded-xl border border-accent/30 bg-surface-2/30 p-4"
          : ""
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={`studio-${meta.key}`} className="text-sm font-semibold text-ink">
          {meta.label}
        </label>
        {meta.badge && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-mono ${
              isSecret
                ? "bg-warn/15 text-warn font-semibold"
                : "border border-accent/40 bg-accent/10 text-accent font-medium"
            }`}
          >
            {meta.badge}
          </span>
        )}
      </div>

      <p id={`studio-${meta.key}-hint`} className="text-xs text-muted leading-relaxed">
        {meta.hint}
      </p>

      <textarea
        id={`studio-${meta.key}`}
        aria-label={meta.label}
        aria-describedby={`studio-${meta.key}-hint`}
        className={`field workshop-field ${isLaws ? "min-h-32" : "min-h-24"}`}
        rows={meta.rows ?? 3}
        placeholder={meta.placeholder}
        value={String(fields[meta.key] ?? "")}
        onChange={(e) => update(meta.key, e.target.value)}
      />

      {meta.tip && (
        <details className="workshop-tip text-xs text-muted">
          <summary className="w-fit cursor-pointer rounded py-0.5 text-patina font-medium transition-colors hover:underline">
            Подсказка: {meta.label.toLowerCase()}
          </summary>
          <p className="mt-1 border-l-2 border-patina pl-3 leading-relaxed text-[11px] text-muted">
            {meta.tip}
          </p>
        </details>
      )}
    </div>
  );
}
