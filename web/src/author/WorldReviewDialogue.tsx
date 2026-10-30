import { useState } from "react";
import type { WorldDraft } from "./WorldDescriptionForm";

export interface DialogueMessage {
  id: string;
  sender: "master" | "author";
  text: string;
  timestamp?: string;
}

export interface ReviewState {
  status: "analyzing" | "questions" | "ready";
  messages: DialogueMessage[];
  pendingQuestions?: string[];
  resolvedSummary?: {
    laws_status: "ok" | "adjusted";
    power_scale: string;
    starter_scene: string;
  };
}

interface Props {
  draft: WorldDraft;
  reviewState: ReviewState;
  onSendMessage: (text: string) => void;
  onProceedToAcceptance: () => void;
  onBackToForm: () => void;
  loading?: boolean;
}

export default function WorldReviewDialogue({
  draft,
  reviewState,
  onSendMessage,
  onProceedToAcceptance,
  onBackToForm,
  loading = false,
}: Props) {
  const [input, setInput] = useState("");

  const handleSend = () => {
    if (!input.trim() || loading) return;
    onSendMessage(input.trim());
    setInput("");
  };

  const isReady = reviewState.status === "ready";

  return (
    <div className="flex flex-col gap-6">
      {/* Навигационная полоса шага */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
        <div>
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
            <span>Шаг 2 · Согласование с мастером</span>
          </div>
          <h2 className="mt-0.5 font-heading text-lg font-bold text-ink">
            Обсуждение мира и проверка законов
          </h2>
          <p className="text-xs text-muted">
            Мастер проверяет непротиворечивость замысла и задаёт адресные вопросы. Ваши ответы уточняют проект.
          </p>
        </div>

        <button
          type="button"
          onClick={onBackToForm}
          className="btn btn-outline-copper self-start sm:self-center h-8 px-3 text-xs font-mono"
        >
          ← Вернуться к полям
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Левая колонка: Интерактивный диалог (2/3 ширины) */}
        <section className="card flex flex-col justify-between border border-line bg-surface lg:col-span-2 min-h-[460px] p-5">
          <div className="flex flex-col gap-4">
            <div className="border-b border-line pb-3 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/15 font-mono text-xs font-bold text-accent">
                  M
                </span>
                <div>
                  <h3 className="font-heading text-sm font-bold text-ink">ИИ-Мастер TaleForge</h3>
                  <p className="font-mono text-[10px] text-muted">
                    {reviewState.status === "analyzing"
                      ? "Анализ непротиворечивости законов…"
                      : isReady
                      ? "Согласование завершено · Проект готов к принятию"
                      : "Ожидание ваших уточнений"}
                  </p>
                </div>
              </div>

              {isReady && (
                <span className="rounded-full bg-patina/15 border border-patina/40 px-2.5 py-0.5 font-mono text-xs font-semibold text-patina-hi">
                  ✓ ВСЁ СОГЛАСОВАНО
                </span>
              )}
            </div>

            {/* Лента сообщений */}
            <div className="flex flex-col gap-3.5 max-h-[380px] overflow-y-auto pr-1">
              {reviewState.messages.map((m) => {
                const isMaster = m.sender === "master";
                return (
                  <div
                    key={m.id}
                    className={`flex flex-col max-w-[88%] rounded-xl p-3.5 text-sm ${
                      isMaster
                        ? "self-start border border-line bg-raised text-ink"
                        : "self-end border border-accent/40 bg-accent/10 text-ink"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted">
                        {isMaster ? "Мастер" : "Автор"}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>
                  </div>
                );
              })}

              {loading && (
                <div className="self-start rounded-xl border border-line bg-raised p-3 text-xs font-mono text-muted animate-pulse">
                  Мастер обдумывает ответ и сверяет законы мира…
                </div>
              )}
            </div>
          </div>

          {/* Форма ответа в чат */}
          <div className="mt-4 border-t border-line pt-3 flex flex-col gap-2">
            {!isReady ? (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSend()}
                  placeholder="Ответьте на вопрос мастера обычными словами…"
                  disabled={loading}
                  className="flex-1 rounded-lg border border-line bg-raised px-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
                />
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={!input.trim() || loading}
                  className="btn btn-primary px-4 py-2 font-mono text-xs font-semibold"
                >
                  ОТВЕТИТЬ
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between rounded-lg bg-patina/10 border border-patina/30 p-3">
                <p className="text-xs text-patina-hi">
                  Все вопросы согласованы. Фундаментальные законы и стартовые условия зафиксированы.
                </p>
                <button
                  type="button"
                  onClick={onProceedToAcceptance}
                  className="btn btn-primary px-4 py-2 font-mono text-xs font-semibold tracking-wider whitespace-nowrap"
                >
                  ПРИНЯТЬ ВЕРСИЮ →
                </button>
              </div>
            )}
          </div>
        </section>

        {/* Правая колонка: Сводка проверяемого мира (1/3 ширины) */}
        <aside className="card flex flex-col gap-4 border border-line bg-surface p-5">
          <div className="border-b border-line pb-2.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted">Снимок проекта</span>
            <h4 className="font-heading text-base font-bold text-ink">{draft.title || "Новый мир"}</h4>
            {draft.premise && <p className="mt-1 text-xs text-muted line-clamp-2">{draft.premise}</p>}
          </div>

          <div className="flex flex-col gap-3 text-xs">
            <div>
              <span className="font-mono font-semibold text-accent">Законы реальности:</span>
              <p className="mt-0.5 text-ink-2 line-clamp-3">
                {draft.laws || "Не указаны (будут определены мастером по умолчанию)"}
              </p>
            </div>

            <div>
              <span className="font-mono font-semibold text-accent">Масштаб сил:</span>
              <p className="mt-0.5 text-ink-2 line-clamp-2">
                {draft.inhabitants || "Стандартный масштаб исследователей"}
              </p>
            </div>

            <div>
              <span className="font-mono font-semibold text-accent">Стартовая ситуация:</span>
              <p className="mt-0.5 text-ink-2 line-clamp-3">
                {draft.start || "Будет предложена мастером на старте"}
              </p>
            </div>

            {draft.secret_text && (
              <div className="rounded-lg border border-warn/30 bg-warn/5 p-2.5">
                <span className="font-mono text-[10px] font-bold uppercase text-warn">
                  Тайны мастера (скрыто от игроков):
                </span>
                <p className="mt-0.5 text-[11px] text-ink line-clamp-2">{draft.secret_text}</p>
              </div>
            )}
          </div>

          {isReady && (
            <div className="mt-auto pt-4 border-t border-line">
              <button
                type="button"
                onClick={onProceedToAcceptance}
                className="btn btn-primary w-full py-2.5 font-mono text-xs font-semibold tracking-wider"
              >
                ПЕРЕЙТИ К ПРИНЯТИЮ ВЕРСИИ →
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

