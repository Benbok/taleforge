import type { SketchExit } from "./map";

export interface PassageBarProps {
  exit: SketchExit;
  destination?: string | null;
  canAct?: boolean;
  pending?: boolean;
  onApproach?: () => void;
  onTraverse?: () => void;
  onInteract?: () => void;
}

export function PassageBar({ exit, destination, canAct = true, pending = false, onApproach, onTraverse, onInteract }: PassageBarProps) {
  const closed = exit.state === "closed" || exit.state === "locked";
  return (
    <div role="group" aria-label={exit.name} data-passage-bar={exit.passage_ref ?? exit.name}>
      <strong>{exit.name}</strong>
      <span>{({ door: "Дверь", bars: "Решётка", window: "Окно", arch: "Арка", stairs: "Лестница", hatch: "Люк", gap: "Проём", passage: "Проход" })[exit.kind]}{exit.state ? `, ${{ open: "открыт", closed: "закрыт", locked: "заперт" }[exit.state]}` : ""}{exit.width ? `, ${exit.width * 5} футов` : ""}</span>
      <span>{destination ?? "Неизвестное место"}</span>
      {closed ? <button type="button" onClick={onApproach} disabled={!canAct}>Подойти</button> : null}
      {closed && onInteract && <button type="button" onClick={onInteract} disabled={!canAct || pending}>Взаимодействовать</button>}
      <button type="button" onClick={onTraverse} disabled={!canAct || pending || closed}>{pending ? "Готовлю проход…" : "Перейти"}</button>
    </div>
  );
}
