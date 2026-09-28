import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useGame } from "../stores/game";
import { useDraft } from "./draft";

let counter = 0;
const clientId = () => `c${Date.now().toString(36)}${(counter++).toString(36)}`;

/** Секунд до конца хода; null — без таймера. */
export function secondsLeft(deadline: number | null | undefined, now: number): number | null {
  if (!deadline) return null;
  return Math.max(0, Math.round(deadline - now / 1000));
}

/** Секунд до хода мастера по окну сбора реплик; null — окна нет или время неизвестно. */
export function waitLeft(createdAt: string | null, windowSec: number, now: number): number | null {
  if (!createdAt || !windowSec) return null;
  return Math.max(0, Math.round((Date.parse(createdAt) + windowSec * 1000 - now) / 1000));
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

/** Поле ввода — нативный чат: игрок пишет как есть, тип реплики определяет сервер. Отдельно только шёпот
 *  мастеру. Что можно сейчас, решает сервер (actions/blocked): закрытое не прячется молча — над полем причина. */
export default function Composer() {
  const { socket, connection, actions, blocked, turn, rejected, notice, snapshot, myPending, restored, clearRestored, addPending, clearRejected } = useGame();
  const { text, whisper, setText, setWhisper } = useDraft();
  const [sendError, setSendError] = useState<string | null>(null);

  const can = (a: string) => actions.includes(a);
  const isMaster = snapshot?.me.role === "master";
  const mainAction = isMaster ? "chat.narrate" : "chat.play";
  const mainOpen = can(mainAction);
  const reason = blocked[mainAction] ?? null;
  const canWhisper = can("chat.whisper");
  const canOoc = can("chat.ooc");
  const myTurn = !!turn && !!snapshot?.me.seat_id && turn.seat_id === snapshot.me.seat_id;
  const now = useNow(!!turn?.deadline);
  const left = myTurn ? secondsLeft(turn?.deadline, now) : null;
  const nowWait = useNow(!!myPending);
  const wait = myPending ? waitLeft(myPending.created_at, snapshot?.collect_window_sec ?? 0, nowWait) : null;

  // отменённая реплика возвращается в поле, чтобы её поправить
  useEffect(() => {
    if (restored === null) return;
    if (!useDraft.getState().text) useDraft.getState().setText(restored);
    clearRestored();
  }, [restored, clearRestored]);

  // отклонённая реплика возвращается в поле, чтобы её можно было поправить
  useEffect(() => {
    if (rejected?.text && !useDraft.getState().text) useDraft.getState().setText(rejected.text);
  }, [rejected]);

  useEffect(() => {
    if (whisper && !canWhisper) setWhisper(false);
  }, [whisper, canWhisper, setWhisper]);

  if (!mainOpen && !canOoc && !canWhisper) {
    return (
      <div className="border-t border-line bg-surface px-4 py-3 text-center text-muted">
        {reason ?? "Вы смотрите кампанию: писать в чат могут только участники."}
      </div>
    );
  }

  const trimmed = text.trim();
  const ooc = trimmed.startsWith("//");
  // что уйдёт при нажатии: так игрок заранее видит, дойдёт ли реплика
  const allowed = whisper ? canWhisper : ooc ? canOoc : mainOpen;
  const hint = whisper
    ? "Шёпот видит только мастер"
    : ooc
      ? "Вне игры: видят все, мастер не отвечает"
      : !mainOpen
        ? reason
        : null;

  function send(e?: FormEvent) {
    e?.preventDefault();
    if (!trimmed) return;
    if (!allowed) {
      setSendError(hint ?? "Сейчас это отправить нельзя.");
      return;
    }
    if (connection !== "open" || !socket) {
      setSendError("Нет связи с сервером: текст сохранён, отправьте после переподключения.");
      return;
    }
    const id = clientId();
    const ok = socket.send("message.send", { kind: whisper ? "whisper" : "auto", text: trimmed, client_id: id });
    if (!ok) {
      setSendError("Нет связи с сервером: текст сохранён, отправьте после переподключения.");
      return;
    }
    addPending({ clientId: id, text: trimmed, whisper, at: Date.now() });
    setSendError(null);
    setText("");
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e as unknown as FormEvent);
  }

  const placeholder = whisper
    ? "Шёпот мастеру…"
    : mainOpen
      ? isMaster
        ? "Повествование…"
        : "Что делает ваш герой?"
      : "Только вне игры: начните с //";

  return (
    <form onSubmit={send} className="flex flex-col gap-2 border-t border-line bg-surface px-4 py-3">
      {myTurn && (
        <p className="tf-pop flex items-center gap-2 font-semibold text-accent" role="status">
          Ваш ход{turn?.round ? `, раунд ${turn.round}` : ""}
          {left !== null && <span className={left <= 15 ? "text-warn" : "text-muted"}>· осталось {left} с</span>}
        </p>
      )}
      {!myTurn && turn && !isMaster && (
        <p className="text-xs text-muted">
          Идёт бой, раунд {turn.round}. Сейчас ход: {turn.name}.
        </p>
      )}
      {rejected && (
        <p role="alert" className="tf-pop flex items-start justify-between gap-2 rounded-md border border-bad px-3 py-2 text-bad">
          <span>Не отправлено: {rejected.reason}</span>
          <button type="button" className="text-xs underline" onClick={clearRejected}>
            скрыть
          </button>
        </p>
      )}
      {notice && !rejected && <p className="tf-pop text-xs text-muted">{notice}</p>}
      {myPending && (
        <p className="text-xs text-muted" role="status">
          Ответ мастера — когда напишут все{wait ? ` или примерно через ${wait} с` : ""}.
        </p>
      )}
      {(sendError || hint) && (
        <p role={sendError ? "alert" : undefined} className={`text-xs ${sendError || !allowed ? "text-warn" : "text-muted"}`}>
          {sendError ?? hint}
        </p>
      )}
      <div className="flex items-end gap-2">
        <textarea
          id="tf-composer"
          className={`field min-h-[2.75rem] flex-1 resize-none ${whisper ? "border-lore italic" : ""}`}
          rows={Math.min(6, Math.max(1, text.split("\n").length))}
          value={text}
          placeholder={placeholder}
          maxLength={4000}
          onChange={(e) => {
            setText(e.target.value);
            if (sendError) setSendError(null);
            if (rejected) clearRejected();
          }}
          onKeyDown={onKey}
          aria-label="Сообщение"
        />
        <button type="submit" className="btn btn-primary h-[2.75rem]" disabled={!trimmed} title="Отправить (Enter)">
          Отправить
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        {canWhisper && (
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={whisper} onChange={(e) => setWhisper(e.target.checked)} />
            Шёпот мастеру
          </label>
        )}
        {can("turn.pass") && (
          <button
            type="button"
            className="btn px-2 py-1 text-xs"
            onClick={() => {
              if (socket?.send("turn.pass")) useGame.setState({ notice: "Пропускаем ход…" });
              else setSendError("Нет связи с сервером: пропустить ход не вышло.");
            }}
          >
            Пропустить ход
          </button>
        )}
        <span className="ml-auto">
          Речь — в кавычках, «//» — вне игры<span className="hidden sm:inline">. Enter — отправить, Shift+Enter — новая строка</span>
        </span>
      </div>
    </form>
  );
}
