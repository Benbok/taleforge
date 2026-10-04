import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "../lib/api";
import type { ChatMessage, PartyPart } from "../lib/types";
import { standInFor, useGame } from "../stores/game";
import { useDraft } from "./draft";
import { clock, MAX_RECORD_SEC, uploadVoice, useRecorder } from "./voice";

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

/** Кому отвечает живой мастер, пока отряд разделён: по умолчанию — части отряда, написавшей последней. */
export function lastPlace(parts: PartyPart[], messages: ChatMessage[]): string | null {
  const ids = new Set(parts.map((p) => p.id));
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if ((m.kind === "action" || m.kind === "speech") && m.data?.place && ids.has(m.data.place)) return m.data.place;
  }
  return null;
}

function useAddressee(parts: PartyPart[], messages: ChatMessage[]) {
  const [picked, setPicked] = useState<{ value: string | null } | null>(null);
  const key = parts.map((p) => p.id).join();
  useEffect(() => setPicked(null), [key]); // отряд сошёлся или разошёлся иначе — выбор снова по последней реплике
  const value = picked ? picked.value : lastPlace(parts, messages);
  return { value: parts.length > 1 ? value : null, set: (v: string | null) => setPicked({ value: v }) };
}

/** Поле ввода — нативный чат: игрок пишет как есть, тип реплики определяет сервер. Отдельно только шёпот
 *  мастеру. Что можно сейчас, решает сервер (actions/blocked): закрытое не прячется молча — над полем причина. */
export default function Composer() {
  const game = useGame();
  const { socket, connection, turn, rejected, notice, snapshot, restored, clearRestored, addPending, clearRejected } = game;
  const { text, whisper, setText, setWhisper } = useDraft();
  const [sendError, setSendError] = useState<string | null>(null);
  // за чьего героя пишем: свой или героя ушедшего игрока, которого передали голосованием
  const standing = standInFor(game);
  const playAs = game.playAs && standing.includes(game.playAs) ? game.playAs : null;
  const alt = playAs ? game.standIn[playAs] : null;
  const actions = playAs ? (alt?.actions ?? game.actions.filter((a) => a === "chat.ooc")) : game.actions;
  const blocked = playAs ? (alt?.blocked ?? {}) : game.blocked;
  const myPending = playAs ? (alt?.pending ?? null) : game.myPending;
  const asSeat = playAs ? { as_seat: playAs } : {};

  const can = (a: string) => actions.includes(a);
  const isMaster = snapshot?.me.role === "master";
  const mainAction = isMaster ? "chat.narrate" : "chat.play";
  const mainOpen = can(mainAction);
  const reason = blocked[mainAction] ?? null;
  const canWhisper = can("chat.whisper");
  const canOoc = can("chat.ooc");
  const actingSeat = playAs ?? snapshot?.me.seat_id ?? null;
  const myTurn = !!turn && !!actingSeat && turn.seat_id === actingSeat;
  const turnSeat = turn?.seat_id ?? null;
  const parts = isMaster ? (game.scene?.party ?? []).filter((p) => p.id) : [];
  const target = useAddressee(parts, game.messages);

  // в бою ходит герой ушедшего, которого ведёт этот игрок: поле само переключается на него
  useEffect(() => {
    if (turnSeat && standing.includes(turnSeat)) useGame.getState().setPlayAs(turnSeat);
    else if (turnSeat && turnSeat === snapshot?.me.seat_id) useGame.getState().setPlayAs(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnSeat, standing.join()]);
  const now = useNow(!!turn?.deadline);
  const left = myTurn ? secondsLeft(turn?.deadline, now) : null;
  const nowWait = useNow(!!myPending);
  const wait = myPending ? waitLeft(myPending.created_at, snapshot?.collect_window_sec ?? 0, nowWait) : null;
  const voiceOn = useQuery({
    queryKey: ["voice"],
    queryFn: () => api<{ enabled: boolean }>("/api/voice"),
    staleTime: 5 * 60_000,
  }).data?.enabled;
  const [uploading, setUploading] = useState(false);
  const rec = useRecorder((blob, seconds) => void sendVoice(blob, seconds));

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
      <div className="flex flex-col gap-2 border-t border-line bg-surface px-4 py-3 text-center text-muted">
        {standing.length > 0 && <PlayAs seats={standing} value={playAs} />}
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
    const to = !whisper && !ooc && target.value ? { place: target.value } : {};
    const ok = socket.send("message.send", { kind: whisper ? "whisper" : "auto", text: trimmed, client_id: id, ...asSeat, ...to });
    if (!ok) {
      setSendError("Нет связи с сервером: текст сохранён, отправьте после переподключения.");
      return;
    }
    addPending({ clientId: id, text: trimmed, whisper, at: Date.now() });
    setSendError(null);
    setText("");
  }

  /** Голосовая уходит в чат сразу: сервер расшифрует её, и под плеером появится текст. */
  async function sendVoice(blob: Blob, seconds: number) {
    const st = useGame.getState();
    const campaignId = st.snapshot?.campaign.id;
    const w = useDraft.getState().whisper;
    if (!campaignId || st.connection !== "open" || !st.socket) {
      setSendError("Нет связи с сервером: голосовое не отправлено, запишите его после переподключения.");
      return;
    }
    setUploading(true);
    try {
      const voice = await uploadVoice(campaignId, blob);
      const id = clientId();
      const payload = { kind: w ? "whisper" : "auto", voice, duration: Math.round(seconds * 10) / 10, client_id: id, ...asSeat };
      if (!st.socket.send("message.send", payload)) throw new Error("нет связи с сервером");
      addPending({ clientId: id, text: "", whisper: w, at: Date.now(), voice: true });
      setSendError(null);
    } catch (e) {
      setSendError(`Голосовое не отправлено: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e as unknown as FormEvent);
  }

  const voiceAllowed = whisper ? canWhisper : mainOpen;
  const voiceReason = voiceAllowed ? null : (reason ?? "Сейчас голосовое отправить нельзя.");
  const recording = rec.state === "recording";

  const placeholder = whisper
    ? "Шёпот мастеру…"
    : mainOpen
      ? isMaster
        ? "Повествование…"
        : playAs
          ? `Что делает ${Object.values(game.heroes).find((h) => h.seat_id === playAs)?.name ?? "герой"}?`
          : "Что делает ваш герой?"
      : "Только вне игры: начните с //";

  return (
    <form onSubmit={send} className="flex flex-col gap-2 border-t border-line bg-surface px-4 py-3">
      {standing.length > 0 && <PlayAs seats={standing} value={playAs} />}
      {parts.length > 1 && (
        <label className="flex items-center gap-2 text-xs text-muted">
          Отряд разделён, ответ слышат:
          <select className="field py-1 text-xs" value={target.value ?? ""} onChange={(e) => target.set(e.target.value || null)}>
            <option value="">все</option>
            {parts.map((p) => (
              <option key={p.id} value={p.id ?? ""}>
                {p.place ?? "место"}: {p.names.join(", ")}
              </option>
            ))}
          </select>
        </label>
      )}
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
          className={`field min-h-[2.75rem] flex-1 resize-none transition-colors ${
            whisper ? "border-accent/70 bg-accent/[0.04] italic text-accent placeholder:text-accent/50" : ""
          }`}
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
        {voiceOn && recording && (
          <button type="button" className="btn h-[2.75rem] px-3" onClick={rec.cancel} title="Не отправлять запись">
            Отмена
          </button>
        )}
        {voiceOn && (
          <button
            type="button"
            className={`btn h-[2.75rem] px-3 ${recording ? "border-bad text-bad" : ""}`}
            disabled={rec.state === "starting" || uploading || (!recording && !voiceAllowed)}
            onClick={() => (recording ? rec.stop() : rec.start())}
            aria-pressed={recording}
            aria-label={recording ? "Остановить и отправить голосовое" : "Записать голосовое"}
            title={recording ? "Остановить и отправить" : (voiceReason ?? "Записать голосовое")}
          >
            {recording ? (
              <span className="flex items-center gap-1.5 font-mono text-sm">
                <span className="h-2 w-2 animate-pulse rounded-full bg-bad" />■ {clock(rec.seconds)}
              </span>
            ) : uploading || rec.state === "starting" ? (
              "…"
            ) : (
              <MicIcon />
            )}
          </button>
        )}
        {!recording && (
          <button type="submit" className="btn btn-primary h-[2.75rem]" disabled={!trimmed} title="Отправить (Enter)">
            Отправить
          </button>
        )}
      </div>
      {recording && (
        <p className="text-xs text-muted" role="status">
          Идёт запись{whisper ? " шёпота мастеру" : ""}: говорите, затем нажмите ■ — голосовое уйдёт в чат, текст
          появится под ним. Не дольше {clock(MAX_RECORD_SEC)}.
        </p>
      )}
      {rec.error && (
        <p role="alert" className="flex items-start justify-between gap-2 text-xs text-warn">
          <span>{rec.error}</span>
          <button type="button" className="underline" onClick={() => rec.setError(null)}>
            скрыть
          </button>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        {canWhisper && (
          <button
            type="button"
            role="checkbox"
            aria-checked={whisper}
            onClick={() => setWhisper(!whisper)}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition cursor-pointer select-none ${
              whisper
                ? "border border-accent/70 bg-accent/15 text-accent shadow-xs"
                : "border border-line/80 bg-raised/70 text-muted hover:border-accent/40 hover:text-ink"
            }`}
            title="Шёпот видит только мастер"
          >
            <span
              className={`h-1.5 w-1.5 rounded-full transition-all ${
                whisper ? "bg-accent shadow-[0_0_6px_var(--tf-accent)]" : "bg-muted/40"
              }`}
            />
            Шёпот мастеру
          </button>
        )}
        {can("turn.pass") && (
          <button
            type="button"
            className="btn px-2 py-1 text-xs"
            onClick={() => {
              if (socket?.send("turn.pass", asSeat)) useGame.setState({ notice: "Пропускаем ход…" });
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

/** Переключатель «играю за»: свой герой или герой ушедшего игрока, которого передали голосованием. */
function PlayAs({ seats, value }: { seats: string[]; value: string | null }) {
  const { heroes, snapshot, seats: all, socket } = useGame();
  const heroOf = (seat: string | null | undefined) => Object.values(heroes).find((h) => h.seat_id === seat);
  const own = heroOf(snapshot?.me.seat_id);
  const pick = (seat: string | null) => {
    useGame.getState().setPlayAs(seat);
    if (seat) socket?.send("actions.get", { as_seat: seat });
  };
  const options: [string | null, string][] = [
    ...(own ? ([[null, own.name]] as [null, string][]) : []),
    ...seats.map((id): [string, string] => {
      const who = all.find((x) => x.id === id)?.user_name;
      return [id, `${heroOf(id)?.name ?? "герой"}${who ? ` (игрок: ${who})` : ""}`];
    }),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm" role="radiogroup" aria-label="За кого пишете">
      <span className="text-muted">Пишете за:</span>
      {options.map(([id, label]) => (
        <button
          key={id ?? "own"}
          type="button"
          role="radio"
          aria-checked={value === id}
          className={`btn px-2 py-1 text-xs ${value === id ? "btn-primary" : ""}`}
          onClick={() => pick(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 17v5" />
    </svg>
  );
}
