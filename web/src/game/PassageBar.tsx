import type { SketchExit } from "./map";

export interface PassageBarProps {
  exit: SketchExit;
  destination?: string | null;
  canAct?: boolean;
  readOnly?: boolean;
  pending?: boolean;
  onApproach?: () => void;
  onTraverse?: () => void;
  onInteract?: () => void;
  onClose?: () => void;
}

export function PassageBar({ exit, destination, canAct = true, pending = false, readOnly = false, onApproach, onTraverse, onInteract, onClose }: PassageBarProps) {
  const closed = exit.state === "closed" || exit.state === "locked" || exit.state === "blocked";
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-accent/40 bg-accent/5 p-3 text-sm" role="group" aria-label={exit.name} data-passage-bar={exit.passage_ref ?? exit.name}>
      <div className="flex items-start justify-between gap-2">
        <div><p className="mb-1 text-xs text-muted">Выбранный проход</p><strong className="break-words text-base text-ink">{exit.name}</strong></div>
        {onClose && <button type="button" className="btn min-h-11 px-3" onClick={onClose} aria-label="Снять выбор прохода">×</button>}
      </div>
      <span className="text-muted">{({ door: "Дверь", bars: "Решётка", window: "Окно", arch: "Арка", stairs: "Лестница", hatch: "Люк", gap: "Проём", passage: "Проход" })[exit.kind]}{exit.state ? `, ${{ open: "открыт", closed: "закрыт", locked: "заперт", blocked: "Путь недоступен" }[exit.state]}` : readOnly ? ", состояние неизвестно" : ""}{exit.width && !readOnly ? `, ${exit.width * 5} футов` : ""}</span>
      <span className="text-ink-2">{exit.orientation?.destination ?? destination ?? (readOnly ? "Куда ведёт — неизвестно" : "Неизвестное место")}</span>
      {readOnly && exit.beyond && <p className="text-ink-2">{exit.beyond}</p>}
      {readOnly && exit.orientation?.approximate && <p className="text-xs text-muted">Положение прохода на схеме условно.</p>}
      {readOnly ? <p className="text-xs text-muted">Карта служит для осмотра. Чтобы действовать, опишите намерение в чате.</p> : <div className="flex flex-wrap gap-2">
        {closed ? <button className="btn min-h-11" type="button" onClick={onApproach} disabled={!canAct || pending}>Подойти</button> : null}
        {closed && onInteract && <button className="btn min-h-11" type="button" onClick={onInteract} disabled={!canAct || pending}>Взаимодействовать</button>}
        <button className="btn btn-primary min-h-11" type="button" onClick={onTraverse} title={closed ? "Сначала откройте проход" : undefined} disabled={!canAct || pending || closed}>{pending ? "Готовлю проход…" : "Перейти"}</button>
      </div>}
    </div>
  );
}
