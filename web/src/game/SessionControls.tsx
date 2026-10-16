import { Link } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";
import { toast } from "../stores/toasts";
import { useGame } from "../stores/game";

/** Управление сессией. Кнопки — только из списка сервера: до старта «Начать», во время — «Пауза» и «Завершить»,
 *  на паузе — «Продолжить». После нажатия сервер пришлёт новое состояние, и кнопки сменятся сами. */
export default function SessionControls({
  campaignId,
  compact = false,
  className = "",
}: {
  campaignId: string;
  compact?: boolean;
  className?: string;
}) {
  const actions = useGame((s) => s.actions);
  const status = useGame((s) => s.snapshot?.campaign.status);
  const notReady = useGame((s) => s.blocked["session.start"]);
  const has = (a: string) => actions.includes(a);
  const session = (action: "start" | "pause" | "end") =>
    api(`/api/campaigns/${campaignId}/session/${action}`, { method: "POST" });

  async function invite() {
    const inv = await api<{ url: string }>(`/api/campaigns/${campaignId}/invites`, { body: {} });
    try {
      await navigator.clipboard.writeText(inv.url);
      toast.ok("Ссылка-приглашение скопирована. Она действует 3 дня.");
    } catch {
      toast.info(`Ссылка-приглашение: ${inv.url}`);
    }
  }

  const hasAnyAction =
    Boolean(notReady) ||
    has("session.start") ||
    has("session.pause") ||
    has("invite.create") ||
    has("campaign.end");

  if (!hasAnyAction) return null;

  const btnClass = compact ? "h-8 px-2.5 text-xs font-mono tracking-wider shrink-0" : "";
  const containerClass = compact
    ? `flex items-center gap-1.5 rounded-[10px] border border-line bg-raised/70 p-1 shrink-0 ${className}`
    : `flex items-center gap-2 shrink-0 ${className}`;

  const hasRoutineActions =
    has("session.start") || has("session.pause") || has("invite.create");

  return (
    <div
      className={containerClass}
      role={compact ? "group" : undefined}
      aria-label={compact ? "Управление сессией" : undefined}
    >
      {notReady && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-warn" role="status">
          {notReady}
          <Link to={`/c/${campaignId}/manage?tab=plot`} className="btn text-xs">
            Открыть «Сюжет»
          </Link>
        </p>
      )}
      {has("session.start") && (
        <ActionButton className={btnClass} primary run={() => session("start")} done={status === "paused" ? "Сессия продолжается" : "Сессия началась"}>
          {status === "paused" ? "Продолжить сессию" : "Начать сессию"}
        </ActionButton>
      )}
      {has("session.pause") && (
        <ActionButton className={btnClass} run={() => session("pause")} done="Сессия на паузе: мастер подведёт итог">
          Пауза
        </ActionButton>
      )}
      {has("invite.create") && (
        <ActionButton className={btnClass} run={invite}>
          Пригласить
        </ActionButton>
      )}
      {has("campaign.end") && (
        <>
          {compact && hasRoutineActions && (
            <span className="h-4 w-px bg-line/80 mx-0.5 shrink-0" aria-hidden="true" />
          )}
          <ActionButton
            danger
            className={btnClass}
            run={() => session("end")}
            done="Кампания завершена"
            confirm="Завершить кампанию насовсем? Мастер напишет эпилог, играть дальше будет нельзя."
          >
            Завершить
          </ActionButton>
        </>
      )}
    </div>
  );
}
