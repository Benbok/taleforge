import { useState, type ReactNode } from "react";
import { toast } from "../stores/toasts";

/** Кнопка с запросом: пока идёт — крутится и не нажимается повторно; успех — уведомление, ошибка — причина
 *  от сервера прямо под кнопкой. */
export default function ActionButton({
  run,
  done,
  children,
  primary,
  danger,
  confirm,
  className = "",
  title,
}: {
  run: () => Promise<unknown>;
  done?: string;
  children: ReactNode;
  primary?: boolean;
  danger?: boolean;
  confirm?: string;
  className?: string;
  title?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function click() {
    if (busy) return;
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    setError(null);
    try {
      await run();
      if (done) toast.ok(done);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      setError(text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col gap-1">
      <button
        className={`btn ${primary ? "btn-primary" : ""} ${danger ? "border-bad text-bad" : ""} ${className}`}
        onClick={click}
        disabled={busy}
        aria-busy={busy}
        title={title}
      >
        {busy && <Spinner />}
        {children}
      </button>
      {error && (
        <span role="alert" className="max-w-xs text-xs text-bad">
          {error}
        </span>
      )}
    </span>
  );
}

export function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
    />
  );
}
