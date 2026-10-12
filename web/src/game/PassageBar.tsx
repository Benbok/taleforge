import type { SketchExit } from "./map";

export interface PassageBarProps {
  exit: SketchExit;
  destination?: string | null;
  canAct?: boolean;
  pending?: boolean;
  onApproach?: () => void;
  onTraverse?: () => void;
}

export function PassageBar({ exit, destination, canAct = true, pending = false, onApproach, onTraverse }: PassageBarProps) {
  const closed = exit.state === "closed" || exit.state === "locked";
  return (
    <div role="group" aria-label={exit.name} data-passage-bar={exit.passage_ref ?? exit.name}>
      <strong>{exit.name}</strong>
      <span>{exit.kind}{exit.state ? `, ${exit.state}` : ""}{exit.width ? `, ${exit.width * 5} футов` : ""}</span>
      <span>{destination ?? "Неизвестное место"}</span>
      {closed ? <button type="button" onClick={onApproach} disabled={!canAct}>Подойти</button> : null}
      <button type="button" onClick={onTraverse} disabled={!canAct || pending || closed}>{pending ? "Готовлю проход…" : "Перейти"}</button>
    </div>
  );
}
