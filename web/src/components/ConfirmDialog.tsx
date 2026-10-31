import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useConfirm } from "../stores/confirm";
import { Spinner } from "./ActionButton";

/** Общее окно подтверждения (монтируется один раз в App). Фокус сначала на «Отмена», фон недоступен. */
export default function ConfirmDialog() {
  const { spec, busy, error, accept, cancel } = useConfirm();
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!spec) return;
    const element = dialog.current!;
    opener.current = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      const back = opener.current;
      if (back?.isConnected) back.focus();
    };
  }, [spec]);

  if (!spec) return null;
  return createPortal(
    <dialog
      ref={dialog}
      aria-labelledby="confirm-title"
      aria-describedby={spec.description ? "confirm-description" : undefined}
      className="m-auto w-[min(92vw,30rem)] rounded-2xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/60"
      onCancel={(event) => {
        event.preventDefault();
        cancel();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) cancel();
      }}
    >
      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 id="confirm-title" className="break-words font-heading text-xl font-bold">
            {spec.title}
          </h2>
          <button
            type="button"
            aria-label="Закрыть"
            disabled={busy}
            onClick={cancel}
            className="btn h-9 w-9 shrink-0 p-0 text-muted disabled:opacity-50"
          >
            ×
          </button>
        </div>
        {spec.description && (
          <p id="confirm-description" className="text-sm leading-relaxed text-muted">
            {spec.description}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-lg border border-bad/40 bg-ember-bg p-3 text-sm text-bad">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-3 pt-2">
          <button type="button" autoFocus className="btn min-h-11 px-4" disabled={busy} onClick={cancel}>
            {spec.cancelLabel ?? "Отмена"}
          </button>
          <button
            type="button"
            aria-busy={busy}
            disabled={busy}
            onClick={() => void accept()}
            className={`btn min-h-11 px-4 font-semibold ${spec.danger ? "border-bad bg-bad/10 text-bad" : "btn-primary"}`}
          >
            {busy && <Spinner />}
            {error ? "Повторить" : (spec.confirmLabel ?? "Подтвердить")}
          </button>
        </div>
      </div>
    </dialog>,
    document.body,
  );
}
