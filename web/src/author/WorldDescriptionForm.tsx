import { useState } from "react";

export interface WorldDraft {
  title: string;
  premise: string;
  world: string;
  laws: string;
  inhabitants: string;
  powers: string;
  history: string;
  start: string;
  style: string;
  secret_text: string;
}

export const EMPTY_WORLD_DRAFT: WorldDraft = {
  title: "",
  premise: "",
  world: "",
  laws: "",
  inhabitants: "",
  powers: "",
  history: "",
  start: "",
  style: "",
  secret_text: "",
};

interface Props {
  draft: WorldDraft;
  onChange: (patch: Partial<WorldDraft>) => void;
  onSubmitForReview: () => void;
  onSaveDraft?: () => void;
  saving?: boolean;
}

export default function WorldDescriptionForm({
  draft,
  onChange,
  onSubmitForReview,
  onSaveDraft,
  saving = false,
}: Props) {
  const [showSecrets, setShowSecrets] = useState(Boolean(draft.secret_text));

  const filledCount = [
    draft.title.trim(),
    draft.premise.trim(),
    draft.world.trim(),
    draft.laws.trim(),
    draft.inhabitants.trim(),
    draft.powers.trim(),
    draft.history.trim(),
    draft.start.trim(),
  ].filter(Boolean).length;

  const totalRequired = 8;
  const canSubmit = draft.title.trim().length > 0 && draft.premise.trim().length > 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Верхняя подсказка и статус */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
        <div>
          <h2 className="font-heading text-lg font-bold text-ink">
            Шаг 1: Опишите мир и фундаментальные законы
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            Заполните ключевые смысловые блоки своими словами. Готовые каталоги классов, рас и монстров не требуются.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 font-mono text-xs text-muted">
            <span>Заполнено:</span>
            <span className="font-semibold text-accent">{filledCount} / {totalRequired}</span>
          </div>
          {onSaveDraft && (
            <button
              type="button"
              onClick={onSaveDraft}
              disabled={saving}
              className="btn btn-outline-copper h-8 px-3 text-xs font-mono"
            >
              {saving ? "Сохранение…" : "Сохранить черновик"}
            </button>
          )}
        </div>
      </div>

      {/* 1. Визитка и замысел */}
      <section className="card flex flex-col gap-4 p-5 sm:p-6 border border-line bg-surface">
        <div className="border-b border-line pb-2.5">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent">
            <span>01 · Основа</span>
          </div>
          <h3 className="font-heading text-base font-bold text-ink">Название и замысел приключения</h3>
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-title" className="text-xs font-medium text-ink">
              Название мира или кампании <span className="text-accent">*</span>
            </label>
            <input
              id="world-title"
              type="text"
              value={draft.title}
              onChange={(e) => onChange({ title: e.target.value })}
              placeholder="Например: Пепельные Архипелаги или Корпорация «Зенит»"
              className="h-10 rounded-lg border border-line bg-raised px-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-premise" className="text-xs font-medium text-ink">
              Главный замысел (в 1–2 предложениях) <span className="text-accent">*</span>
            </label>
            <textarea
              id="world-premise"
              rows={2}
              value={draft.premise}
              onChange={(e) => onChange({ premise: e.target.value })}
              placeholder="О чём эта история, в какой эпохе разворачивается и каков центральный мотив"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      </section>

      {/* 2. Устройство и законы реальности */}
      <section className="card flex flex-col gap-4 p-5 sm:p-6 border border-line bg-surface">
        <div className="border-b border-line pb-2.5">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent">
            <span>02 · Законы реальности</span>
          </div>
          <h3 className="font-heading text-base font-bold text-ink">Устройство мира и фундаментальные законы</h3>
          <p className="mt-0.5 text-xs text-muted">
            ИИ-мастер будет строго соблюдать эти правила. Он не сможет молча переписать или нарушить ваши фундаментальные законы.
          </p>
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-device" className="text-xs font-medium text-ink">
              Устройство мира: география, цивилизации, технологии и повседневность
            </label>
            <textarea
              id="world-device"
              rows={3}
              value={draft.world}
              onChange={(e) => onChange({ world: e.target.value })}
              placeholder="Климат, материки, устройство городов, доступность связи, быт обычных жителей…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-laws" className="text-xs font-medium text-ink">
              Фундаментальные законы: что абсолютно возможно, а что невозможно
            </label>
            <textarea
              id="world-laws"
              rows={3}
              value={draft.laws}
              onChange={(e) => onChange({ laws: e.target.value })}
              placeholder="Действует ли магия, какова её цена; можно ли воскрешать мёртвых; есть ли псионика или сверхсветовые перемещения…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      </section>

      {/* 3. Обитатели, силы и способности */}
      <section className="card flex flex-col gap-4 p-5 sm:p-6 border border-line bg-surface">
        <div className="border-b border-line pb-2.5">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent">
            <span>03 · Силы и обитатели</span>
          </div>
          <h3 className="font-heading text-base font-bold text-ink">Обитатели, способности и масштаб начальных возможностей</h3>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-inhabitants" className="text-xs font-medium text-ink">
              Обитатели мира и начальный масштаб героев
            </label>
            <textarea
              id="world-inhabitants"
              rows={3}
              value={draft.inhabitants}
              onChange={(e) => onChange({ inhabitants: e.target.value })}
              placeholder="Какие виды и народы населяют мир; герои — обычные смертные, тренированные исследователи или полубоги…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-powers" className="text-xs font-medium text-ink">
              Принципы способностей, источники сил и ограничения
            </label>
            <textarea
              id="world-powers"
              rows={3}
              value={draft.powers}
              onChange={(e) => onChange({ powers: e.target.value })}
              placeholder="Как герои творят чудеса: через внутреннюю энергию, импланты, молитвы, древние артефакты…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      </section>

      {/* 4. История, начало и атмосфера */}
      <section className="card flex flex-col gap-4 p-5 sm:p-6 border border-line bg-surface">
        <div className="border-b border-line pb-2.5">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent">
            <span>04 · Приключение и атмосфера</span>
          </div>
          <h3 className="font-heading text-base font-bold text-ink">Начало приключения, атмосфера и ведение</h3>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-history" className="text-xs font-medium text-ink">
              История, действующие силы и конфликты
            </label>
            <textarea
              id="world-history"
              rows={3}
              value={draft.history}
              onChange={(e) => onChange({ history: e.target.value })}
              placeholder="Ключевые фракции, недавняя война или надвигающаяся катастрофа, за кем власть…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="world-start" className="text-xs font-medium text-ink">
              Начало приключения: стартовая ситуация и зацепка
            </label>
            <textarea
              id="world-start"
              rows={3}
              value={draft.start}
              onChange={(e) => onChange({ start: e.target.value })}
              placeholder="Где отряд оказывается в первый миг, какая немедленная задача стоит перед исследователями…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>

          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <label htmlFor="world-style" className="text-xs font-medium text-ink">
              Ведение: атмосфера, подробность повествования, исключённые темы (табу)
            </label>
            <textarea
              id="world-style"
              rows={2}
              value={draft.style}
              onChange={(e) => onChange({ style: e.target.value })}
              placeholder="Мрачное выживание, таинственный детектив или героический эпос; темы, которые мастер должен исключить…"
              className="rounded-lg border border-line bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      </section>

      {/* 5. Тайны мастера (приватный блок) */}
      <section className="card flex flex-col gap-3 p-5 sm:p-6 border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-heading text-base font-bold text-ink">Тайны автора (секреты мастера)</span>
              <span className="rounded-full bg-warn/15 px-2 py-0.5 font-mono text-[10px] font-semibold text-warn">
                ТОЛЬКО ДЛЯ МАСТЕРА
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted">
              Сведения, которые знает ИИ-мастер для ведения интриги, но которые никогда не попадут в публичное описание для игроков.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSecrets(!showSecrets)}
            className="btn btn-outline-copper h-8 px-3 text-xs font-mono"
          >
            {showSecrets ? "Скрыть блок тайн" : "+ Добавить авторские секреты"}
          </button>
        </div>

        {showSecrets && (
          <div className="mt-2 flex flex-col gap-1.5 border-t border-line/60 pt-3">
            <label htmlFor="world-secrets" className="text-xs font-medium text-ink">
              Скрытые факты, истинные мотивы NPC, запретные тайны и невидимые угрозы
            </label>
            <textarea
              id="world-secrets"
              rows={3}
              value={draft.secret_text}
              onChange={(e) => onChange({ secret_text: e.target.value })}
              placeholder="Например: главный советник на самом деле служит потусторонней сущности; за древними вратами спрятан генератор коллапса…"
              className="rounded-lg border border-warn/40 bg-raised p-3 text-sm text-ink placeholder:text-muted/60 focus:border-warn focus:outline-none"
            />
          </div>
        )}
      </section>

      {/* Нижняя панель действий */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface p-4">
        <div className="text-xs text-muted">
          {!canSubmit
            ? "Укажите название и главный замысел мира, чтобы отправить черновик на проверку мастеру."
            : "Мастер проверит согласованность законов и задаст адресные вопросы при необходимости."}
        </div>

        <button
          type="button"
          onClick={onSubmitForReview}
          disabled={!canSubmit}
          className="btn btn-primary px-5 py-2.5 font-mono text-xs font-semibold tracking-wider"
        >
          ОТПРАВИТЬ МАСТЕРУ НА ПРОВЕРКУ →
        </button>
      </div>
    </div>
  );
}

