import { useEffect, useState } from "react";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";

/** Кнопка реакции: крупно, поверх поля ввода, с полосой оставшегося времени. Не ответили — реакция не тратится. */
export default function ReactionPanel() {
  const reaction = useGame((s) => s.reaction);
  const socket = useGame((s) => s.socket);
  const [chosen, setChosen] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setChosen(null);
    if (!reaction) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [reaction]);

  if (!reaction) return null;
  const left = Math.max(0, Math.ceil(reaction.expires_at - now / 1000));

  function choose(option: string) {
    if (chosen || !reaction) return;
    if (!socket?.send("reaction.choose", { prompt_id: reaction.prompt_id, option })) {
      toast.error("Нет связи с сервером: реакция не отправлена.");
      return;
    }
    setChosen(option);
  }

  return (
    <div
      role="alertdialog"
      aria-label="Реакция"
      className="tf-pop border-t-2 border-accent bg-raised px-4 py-3"
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="font-semibold">Реакция: {reaction.trigger}</p>
        <span className={`tabular-nums text-sm ${left <= 5 ? "text-bad" : "text-muted"}`}>{left} с</span>
      </div>
      <div className="mb-3 h-1 overflow-hidden rounded-full bg-surface">
        <div
          key={reaction.prompt_id}
          className="h-full origin-left bg-accent"
          style={{ animation: `tf-drain ${Math.max(0, reaction.expires_at - Date.now() / 1000)}s linear forwards` }}
        />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        {reaction.options.map((o) => (
          <button
            key={o.id}
            className={`btn flex-1 py-3 text-base ${o.id === "skip" ? "" : "btn-primary"}`}
            disabled={!!chosen}
            onClick={() => choose(o.id)}
          >
            {chosen === o.id ? "Отправлено…" : o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
