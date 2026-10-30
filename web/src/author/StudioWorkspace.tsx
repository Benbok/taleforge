import { useState, useEffect } from "react";
import WorldDescriptionForm, { EMPTY_WORLD_DRAFT, type WorldDraft } from "./WorldDescriptionForm";
import WorldReviewDialogue, { type ReviewState } from "./WorldReviewDialogue";
import WorldVersionCard, { type AcceptedVersion } from "./WorldVersionCard";

export type StudioStep = "describe" | "review" | "version";

interface Props {
  projectId: string;
  initialStep?: StudioStep;
  initialDraft?: Partial<WorldDraft>;
  initialVersion?: AcceptedVersion | null;
  onSaveDraft?: (draft: WorldDraft) => Promise<void>;
  onAcceptVersion?: (draft: WorldDraft) => Promise<AcceptedVersion>;
  onLaunchAdventure?: (version: AcceptedVersion) => void;
}

export default function StudioWorkspace({
  projectId,
  initialStep = "describe",
  initialDraft,
  initialVersion = null,
  onSaveDraft,
  onAcceptVersion,
  onLaunchAdventure,
}: Props) {
  const draftKey = `studio:draft:${projectId}`;
  const stepKey = `studio:step:${projectId}`;

  const [step, setStep] = useState<StudioStep>(() => {
    if (initialVersion) return "version";
    try {
      const saved = localStorage.getItem(stepKey) as StudioStep | null;
      if (saved && ["describe", "review", "version"].includes(saved)) return saved;
    } catch {
      // ignore
    }
    return initialStep;
  });

  const [draft, setDraft] = useState<WorldDraft>(() => {
    try {
      const saved = localStorage.getItem(draftKey);
      if (saved) return { ...EMPTY_WORLD_DRAFT, ...JSON.parse(saved) };
    } catch {
      // ignore
    }
    return { ...EMPTY_WORLD_DRAFT, ...initialDraft };
  });

  const [version, setVersion] = useState<AcceptedVersion | null>(initialVersion);
  const [saving, setSaving] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);

  // Состояние диалога ревью с мастером
  const [reviewState, setReviewState] = useState<ReviewState>(() => ({
    status: "questions",
    messages: [
      {
        id: "msg-1",
        sender: "master",
        text: `Приветствую, автор. Я внимательно изучил описание мира «${
          draft.title || "Черновик"
        }».\n\nФундаментальные законы выглядят устойчиво. Однако мне нужно уточнить пару деталей:\n1. Если магия доступна исследователям, как она сосуществует с технологическим уровнем?\n2. Какая главная опасность подстерегает отряд в стартовой точке?`,
      },
    ],
  }));

  // Автосохранение черновика
  useEffect(() => {
    try {
      localStorage.setItem(draftKey, JSON.stringify(draft));
      localStorage.setItem(stepKey, step);
    } catch {
      // ignore
    }
  }, [draft, step, draftKey, stepKey]);

  // Подхватываем данные проекта при асинхронной загрузке
  useEffect(() => {
    if (initialDraft) {
      setDraft((prev) => {
        let changed = false;
        const next = { ...prev };
        if (!prev.title && initialDraft.title) {
          next.title = initialDraft.title;
          changed = true;
        }
        if (!prev.premise && initialDraft.premise) {
          next.premise = initialDraft.premise;
          changed = true;
        }
        return changed ? next : prev;
      });
    }
  }, [initialDraft]);

  useEffect(() => {
    if (initialVersion && !version) {
      setVersion(initialVersion);
      setStep("version");
    }
  }, [initialVersion, version]);

  const handleDraftChange = (patch: Partial<WorldDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const handleSaveDraft = async () => {
    setSaving(true);
    try {
      if (onSaveDraft) await onSaveDraft(draft);
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitForReview = () => {
    setReviewLoading(true);
    setStep("review");
    // Инициализируем диалог ревью мастера
    setTimeout(() => {
      setReviewState({
        status: "questions",
        messages: [
          {
            id: `msg-${Date.now()}`,
            sender: "master",
            text: `Черновик мира «${draft.title}» принят на рассмотрение.\n\nЗамысел понятен: «${draft.premise}».\n\nЗаконы реальности: ${
              draft.laws || "Стандартные"
            }.\n\nУточните, пожалуйста: каков уровень угрозы для отряда в первые минуты после входа в приключение?`,
          },
        ],
      });
      setReviewLoading(false);
    }, 600);
  };

  const handleSendDialogueMessage = (text: string) => {
    const userMsg = { id: `user-${Date.now()}`, sender: "author" as const, text };
    setReviewState((prev) => ({ ...prev, messages: [...prev.messages, userMsg] }));
    setReviewLoading(true);

    // Мастер отвечает и финализирует согласование
    setTimeout(() => {
      const masterMsg = {
        id: `master-${Date.now()}`,
        sender: "master" as const,
        text: `Благодарю за уточнение! «${text}» зафиксировано в правилах мира. Противоречий нет, законы согласованы.\n\nПаспорт мира готов. Вы можете принять неизменяемую версию и запускать независимые приключения.`,
      };
      setReviewState((prev) => ({
        ...prev,
        status: "ready",
        messages: [...prev.messages, masterMsg],
      }));
      setReviewLoading(false);
    }, 800);
  };

  const handleProceedToAcceptance = async () => {
    if (onAcceptVersion) {
      const newVersion = await onAcceptVersion(draft);
      setVersion(newVersion);
    } else {
      setVersion({
        version: "v1.0",
        published_at: new Date().toISOString(),
        adventure_id: projectId,
        draft_revision: 1,
      });
    }
    setStep("version");
  };

  const STEPS: { id: StudioStep; label: string; number: string }[] = [
    { id: "describe", label: "Опишите мир", number: "1" },
    { id: "review", label: "Обсудите с мастером", number: "2" },
    { id: "version", label: "Примите версию", number: "3" },
  ];

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
      {/* Terminal Header */}
      <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
        <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
              <span>Творческая студия · TaleForge</span>
            </div>
            <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
              {draft.title || "Новый мир и кампания"}
            </h1>
            <p className="mt-1 text-xs sm:text-sm text-muted">
              Опишите мир, согласуйте законы с мастером и зафиксируйте неизменяемую версию для независимых столов.
            </p>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3 py-1.5 rounded-full border border-line bg-raised text-ink-2">
            <span>СТАТУС:</span>
            <span className="font-semibold text-accent uppercase">
              {step === "describe" ? "Черновик" : step === "review" ? "Согласование" : "Версия принята"}
            </span>
          </div>
        </div>
      </div>

      {/* 3-шаговый StepBar */}
      <nav aria-label="Шаги творческой студии" className="grid grid-cols-3 gap-2 sm:gap-4 border-b border-line pb-4">
        {STEPS.map((s) => {
          const isActive = step === s.id;
          const isPassed =
            (s.id === "describe" && (step === "review" || step === "version")) ||
            (s.id === "review" && step === "version");

          return (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                // Разрешаем переход на пройденные шаги или на шаг ревью, если черновик заполнен
                if (isPassed || (s.id === "describe") || (s.id === "review" && draft.title.trim())) {
                  setStep(s.id);
                }
              }}
              className={`flex items-center gap-2.5 rounded-xl border p-3 text-left transition-all ${
                isActive
                  ? "border-accent bg-accent/10 text-ink shadow-sm"
                  : isPassed
                  ? "border-patina/40 bg-surface text-ink hover:border-patina"
                  : "border-line bg-surface/50 text-muted opacity-75"
              }`}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-xs font-bold ${
                  isActive
                    ? "bg-accent text-white"
                    : isPassed
                    ? "bg-patina text-white"
                    : "bg-line text-muted"
                }`}
              >
                {isPassed ? "✓" : s.number}
              </span>
              <div className="flex flex-col min-w-0">
                <span className="truncate text-xs font-semibold leading-tight">{s.label}</span>
                <span className="font-mono text-[10px] text-muted">
                  {s.id === "describe"
                    ? "Замысел и законы"
                    : s.id === "review"
                    ? "Проверка мастера"
                    : "Запуск столов"}
                </span>
              </div>
            </button>
          );
        })}
      </nav>

      {/* Содержимое активного шага */}
      {step === "describe" && (
        <WorldDescriptionForm
          draft={draft}
          onChange={handleDraftChange}
          onSubmitForReview={handleSubmitForReview}
          onSaveDraft={handleSaveDraft}
          saving={saving}
        />
      )}

      {step === "review" && (
        <WorldReviewDialogue
          draft={draft}
          reviewState={reviewState}
          onSendMessage={handleSendDialogueMessage}
          onProceedToAcceptance={handleProceedToAcceptance}
          onBackToForm={() => setStep("describe")}
          loading={reviewLoading}
        />
      )}

      {step === "version" && version && (
        <WorldVersionCard
          draft={draft}
          version={version}
          onEditNewVersion={() => setStep("describe")}
          onLaunchAdventure={
            onLaunchAdventure ? () => onLaunchAdventure(version) : undefined
          }
        />
      )}
    </main>
  );
}

