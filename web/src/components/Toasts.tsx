import { useToasts } from "../stores/toasts";

const TONE = {
  ok: "border-ok",
  error: "border-bad",
  info: "border-accent",
};
const ICON = { ok: "✓", error: "!", info: "i" };

/** Уведомления внизу экрана: результат действия и понятная причина ошибки. */
export default function Toasts() {
  const { items, dismiss } = useToasts();
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-auto md:top-16 md:items-end"
    >
      {items.map((t) => (
        <div
          key={t.id}
          role={t.tone === "error" ? "alert" : "status"}
          className={`tf-pop pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border-l-4 bg-raised px-4 py-3 shadow-lg ${TONE[t.tone]}`}
        >
          <span
            className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
              t.tone === "error" ? "bg-bad text-white" : t.tone === "ok" ? "bg-ok text-white" : "bg-accent text-on-accent"
            }`}
            aria-hidden
          >
            {ICON[t.tone]}
          </span>
          <p className="flex-1">{t.text}</p>
          <button className="text-muted hover:text-ink" onClick={() => dismiss(t.id)} aria-label="Закрыть">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
