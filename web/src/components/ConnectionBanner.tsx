import { useGame } from "../stores/game";

/** Плашка над содержимым, пока соединения нет. Набранный текст при этом не теряется. */
export default function ConnectionBanner() {
  const { connection, connectionDetail } = useGame();
  if (connection === "open") return null;
  const text =
    connectionDetail === "unauthorized"
      ? "Вход устарел: войдите заново."
      : connection === "connecting"
        ? "Подключаемся…"
        : connection === "reconnecting"
          ? "Переподключаемся…"
          : "Соединение закрыто.";
  return (
    <div role="status" className="border-b border-warn bg-raised px-4 py-2 text-center text-warn">
      {text}
    </div>
  );
}
