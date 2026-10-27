import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "../lib/api";
import type { ChatMessage, PartyPart } from "../lib/types";
import type { ExplorationState } from "./ExplorationPanel";
import { standInFor, useGame } from "../stores/game";
import { useDraft } from "./draft";
import { clock, MAX_RECORD_SEC, uploadVoice, useRecorder } from "./voice";
import { STAGES } from "./masterStatus";

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
  const { text, whisper, quick, setText, setWhisper } = useDraft();
  const [sendError, setSendError] = useState<string | null>(null);
  const responding = !!game.masterStage && !!STAGES[game.masterStage];
  const [responseStarted, setResponseStarted] = useState<number | null>(null);
  useEffect(() => { setResponseStarted(responding ? Date.now() : null); }, [responding]);
  const responseNow = useNow(responding);
  const slowResponse = responding && responseStarted !== null && responseNow - responseStarted >= 30000;
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
  const [showQuickMenu, setShowQuickMenu] = useState(false);
  const quickMenuContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showQuickMenu) return;
    const onClickOutside = (e: MouseEvent) => {
      if (quickMenuContainerRef.current && !quickMenuContainerRef.current.contains(e.target as Node)) {
        setShowQuickMenu(false);
      }
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setShowQuickMenu(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      window.removeEventListener("keydown", onKey);
    };
  }, [showQuickMenu]);

  // Активные эффекты, превращения и временные состояния героя
  const sheet = game.sheet as unknown as {
    exploration?: ExplorationState;
    derived?: {
      effects?: { id: string; template: string; name: string; stacks: number; reason?: string | null }[];
    };
  } | null;
  const exploration = sheet?.exploration;
  const expEffects = exploration?.effects ?? [];
  const derivedEffects = (sheet?.derived?.effects ?? []).filter(
    (e) => !expEffects.some((x) => x.id === e.id || x.label === e.name)
  );
  const hasExpEffects = expEffects.length > 0;
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
  const hasContent = !!(ooc && !whisper ? trimmed.slice(2).trim() : trimmed);
  const messageMode = whisper ? "whisper" : ooc ? "ooc" : "game";
  function selectMode(mode: "game" | "ooc" | "whisper") {
    const content = text.replace(/^\s*\/\/\s?/, "");
    setWhisper(mode === "whisper");
    setText(mode === "ooc" ? `// ${content}` : content);
    setSendError(null);
    document.getElementById("tf-composer")?.focus();
  }
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
    if (!hasContent) return;
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
    const picked = !whisper && !ooc && !isMaster && quick ? { quick: { actions: quick } } : {};
    const ok = socket.send("message.send", { kind: whisper ? "whisper" : "auto", text: trimmed, client_id: id, ...asSeat, ...to, ...picked });
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

  const voiceAllowed = whisper ? canWhisper : !ooc && mainOpen;
  const voiceReason = voiceAllowed ? null : ooc ? "Вне игры можно отправить текст. Для голосового выберите «В игре» или «Шёпот»." : (reason ?? "Сейчас голосовое отправить нельзя.");
  const recording = rec.state === "recording";

  const placeholder = ooc && !whisper
    ? "Сообщение вне игры…"
    : whisper
    ? "Шёпот мастеру…"
    : mainOpen
      ? isMaster
        ? "Повествование…"
        : playAs
          ? `Что делает ${Object.values(game.heroes).find((h) => h.seat_id === playAs)?.name ?? "герой"}?`
          : "Что делает ваш герой?"
      : "Только вне игры: начните с //";

  const quickPrompts =
    messageMode === "whisper"
      ? [
          { label: "Спросить мастера", icon: "💭", text: "Спрашиваю мастера: " },
          { label: "Тайное действие", icon: "🤫", text: "Хочу сделать скрытно от отряда: " },
          { label: "Проверить знание", icon: "🎲", text: "Что мой персонаж может помнить об этом?" },
        ]
      : messageMode === "game"
        ? [
            ...(game.scene?.entities ?? []).slice(0, 2).map((e) => ({
              label: `${e.kind === "item" ? "Осмотреть" : e.attitude === "hostile" ? "К цели:" : "К:"} ${e.name}`,
              icon: e.kind === "item" ? "◆" : e.attitude === "hostile" ? "⚔" : "💬",
              text:
                e.kind === "item"
                  ? `Осматриваю: ${e.name}`
                  : e.attitude === "hostile"
                    ? `Слежу за действиями: ${e.name}`
                    : `Обращаюсь к: ${e.name} — `,
              action: { verb: "inspect", target_id: e.id },
            })),
            { label: "Осмотреться", icon: "👁️", text: "Внимательно осматриваюсь вокруг." },
            { label: "Прислушаться", icon: "👂", text: "Прислушиваюсь к звукам и шорохам." },
            { label: "Исследовать", icon: "🔍", text: "Изучаю детали обстановки: " },
            { label: "Подойти ближе", icon: "👣", text: "Осторожно приближаюсь... " },
            { label: "Затаиться", icon: "✋", text: "Пытаюсь затаиться и не привлекать внимания." },
          ]
        : [];

  return (
    <form
      onSubmit={send}
      className="tf-composer flex flex-col gap-1.5 border-t border-line/80 bg-surface/95 px-3 py-2 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur-xs sm:px-4"
    >
      {standing.length > 0 && <PlayAs seats={standing} value={playAs} />}

      {/* Табы режима: В игре, Вне игры, Шёпот */}
      <div
        className="flex flex-wrap gap-1 rounded-lg border border-line/70 bg-raised/70 p-0.5 backdrop-blur-xs"
        role="group"
        aria-label="Режим сообщения"
      >
        {([
          ["game", "В игре", mainOpen, "⚔"],
          ["ooc", "Вне игры", canOoc, "💬"],
          ["whisper", "Шёпот", canWhisper, "🗝️"],
        ] as const).map(([value, tabLabel, available, icon]) => (
          <button
            key={value}
            type="button"
            aria-pressed={messageMode === value}
            disabled={!available || recording || uploading || rec.state === "starting"}
            title={
              !available
                ? blocked[value === "game" ? mainAction : `chat.${value}`] ?? "Сейчас недоступно"
                : value === "whisper"
                  ? "Сообщение видите только вы и мастер"
                  : undefined
            }
            className={`flex min-h-7.5 flex-1 items-center justify-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition-all sm:min-h-7.5 disabled:cursor-not-allowed disabled:opacity-40 ${
              messageMode === value
                ? "border border-accent/40 bg-surface text-accent shadow-xs ring-1 ring-accent/20"
                : "border border-transparent text-muted hover:bg-surface/50 hover:text-ink"
            }`}
            onClick={() => selectMode(value)}
          >
            <span className="shrink-0 text-xs" aria-hidden="true">
              {icon}
            </span>
            <span>{tabLabel}</span>
          </button>
        ))}
      </div>

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

      {/* Статус хода в бою или ожидание других игроков отряда */}
      {(myTurn || (myPending && !responding) || (turn && !isMaster)) && (
        <div
          className={`flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-lg border px-2.5 py-1 text-xs transition-all ${
            myTurn
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-line bg-raised text-ink-2"
          }`}
          role="status"
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 shrink-0 rounded-full ${myTurn ? "bg-accent" : "bg-muted"}`}
          />
          <span className="font-semibold">
            {myTurn
              ? "Ваш ход"
              : myPending
                ? "Ожидаем остальных игроков"
                : `Сейчас ход: ${turn?.name}`}
          </span>
          {turn && <span className="text-muted">· раунд {turn.round}</span>}
          {myTurn && left !== null && <span className={left <= 15 ? "text-warn" : "text-muted"}>· осталось {left} с</span>}
          {myPending && !myTurn && (
            <span className="text-muted">· мастер ответит, когда напишут все{wait ? ` или примерно через ${wait} с` : ""}</span>
          )}
        </div>
      )}

      {slowResponse && (
        <p className="text-xs text-muted" role="status">
          Ответ занимает больше времени. Повторно отправлять реплику не нужно.
        </p>
      )}

      {rejected && (
        <p role="alert" className="tf-pop flex items-start justify-between gap-2 rounded-md border border-bad px-2.5 py-1.5 text-xs text-bad">
          <span>Не отправлено: {rejected.reason}</span>
          <button type="button" className="text-xs underline" onClick={clearRejected}>
            скрыть
          </button>
        </p>
      )}

      {notice && !rejected && <p className="tf-pop text-xs text-muted">{notice}</p>}

      {(sendError || hint) && (
        <p role={sendError ? "alert" : undefined} className={`text-xs ${sendError || !allowed ? "text-warn" : "text-muted"}`}>
          {sendError ?? hint}
        </p>
      )}

      {/* Активные эффекты и состояния героя над строкой ввода */}
      {(hasExpEffects || derivedEffects.length > 0) && (
        <div
          className="tf-composer-effects flex flex-wrap items-center gap-1.5 rounded-lg border border-line-soft bg-surface-2/40 px-2.5 py-1.5 text-xs"
          aria-label="Активные эффекты героя"
        >
          <div className="flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-patina mr-1 shrink-0">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" aria-hidden="true" />
            <span>Эффекты:</span>
          </div>

          {expEffects.map((ef) => (
            <div
              key={ef.id}
              className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-0.5 text-xs text-ink shadow-2xs hover:border-accent/60 transition-colors"
              title={
                ef.kind === "camouflage"
                  ? "Помогает скрываться при наличии укрытия. Свидетели помнят героя."
                  : ef.kind === "illumination"
                  ? "Освещает место, помогая рассмотреть доступные детали."
                  : ef.label
              }
            >
              <span className="text-accent text-[11px]" aria-hidden="true">✦</span>
              <span className="font-medium">{ef.label}</span>
              {ef.remaining_seconds && (
                <span className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.2 font-mono text-[10px] font-bold text-accent whitespace-nowrap">
                  <span className="text-[9px]">⏱</span>
                  <span>{ef.remaining_seconds} с</span>
                </span>
              )}
            </div>
          ))}

          {derivedEffects.map((ef) => (
            <div
              key={ef.id}
              className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-0.5 text-xs text-ink shadow-2xs"
              title={ef.reason || ef.name}
            >
              <span className="text-patina text-[11px]" aria-hidden="true">✦</span>
              <span className="font-medium">{ef.name}</span>
              {ef.stacks > 1 && (
                <span className="rounded bg-patina/10 px-1 font-mono text-[10px] font-bold text-patina">
                  ×{ef.stacks}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Поле ввода с кнопкой быстрых действий ⚡ и отправкой */}
      <div className="flex items-end gap-2">
        {quickPrompts.length > 0 && !recording && mainOpen && (
          <div ref={quickMenuContainerRef} className="relative shrink-0">
            <button
              type="button"
              className={`tf-quick-btn btn h-[2.5rem] w-[2.5rem] rounded-xl p-0 flex items-center justify-center transition-all ${
                showQuickMenu
                  ? "border-accent bg-accent/20 text-accent ring-1 ring-accent/30 shadow-xs"
                  : "border-line/80 bg-raised/50 text-muted hover:border-accent/60 hover:text-ink"
              }`}
              onClick={() => setShowQuickMenu((v) => !v)}
              title="Быстрые действия (осмотреться, затаиться...)"
              aria-label="Быстрые действия"
              aria-haspopup="menu"
              aria-expanded={showQuickMenu}
            >
              <span aria-hidden="true" className="text-sm">⚡</span>
            </button>
            {showQuickMenu && (
              <div
                className="tf-pop absolute bottom-full left-0 mb-2 z-30 min-w-[13.5rem] max-w-[18rem] rounded-xl border border-line bg-surface p-1.5 shadow-xl backdrop-blur-md"
                role="menu"
                aria-label="Быстрые действия"
              >
                <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-patina border-b border-line-soft/50 mb-1 flex items-center justify-between">
                  <span>Быстрые действия</span>
                  <span className="text-[9px] text-muted font-normal lowercase">Esc</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  {quickPrompts.map((p, idx) => (
                    <button
                      key={idx}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        useDraft.getState().insert(p.text, "action" in p ? p.action : undefined);
                        setShowQuickMenu(false);
                        document.getElementById("tf-composer")?.focus();
                      }}
                      className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-ink hover:bg-raised/90 hover:text-accent transition-colors"
                      title={p.text}
                    >
                      <span aria-hidden="true" className="text-sm shrink-0">{p.icon}</span>
                      <span className="font-medium truncate">{p.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <textarea
          id="tf-composer"
          className={`field min-h-[2.5rem] min-w-0 flex-1 resize-none rounded-xl border p-2 font-ui text-base transition-all sm:text-sm ${
            whisper
              ? "border-accent/70 bg-accent/[0.04] italic text-ink placeholder:text-accent/50 focus:border-accent focus:ring-1 focus:ring-accent/30"
              : "border-line/80 bg-raised/40 focus:border-accent/80 focus:bg-surface focus:ring-1 focus:ring-accent/30"
          }`}
          rows={Math.min(5, Math.max(1, text.split("\n").length))}
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
          <button type="button" className="btn h-[2.5rem] rounded-xl px-2.5 text-xs" onClick={rec.cancel} title="Не отправлять запись">
            Отмена
          </button>
        )}
        {voiceOn && (
          <button
            type="button"
            className={`btn h-[2.5rem] rounded-xl px-2.5 ${recording ? "border-bad text-bad" : ""}`}
            disabled={rec.state === "starting" || uploading || (!recording && !voiceAllowed)}
            onClick={() => (recording ? rec.stop() : rec.start())}
            aria-pressed={recording}
            aria-label={recording ? "Остановить и отправить голосовое" : "Записать голосовое"}
            title={recording ? "Остановить и отправить" : (voiceReason ?? "Записать голосовое")}
          >
            {recording ? (
              <span className="flex items-center gap-1 font-mono text-xs">
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
          <button
            type="submit"
            className="btn btn-primary group relative flex h-[2.5rem] min-w-10 shrink-0 items-center justify-center gap-1.5 rounded-xl px-3 shadow-xs transition-all disabled:opacity-40"
            disabled={!hasContent}
            title="Отправить (Enter)"
            aria-label="Отправить сообщение"
          >
            <D20Icon className="h-4 w-4 shrink-0 transition-transform group-hover:rotate-12 group-active:scale-95" />
            <span className="hidden font-heading text-xs font-bold sm:inline">Отправить</span>
            <span className="text-xs font-bold sm:hidden" aria-hidden="true">
              ↑
            </span>
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
        {can("turn.pass") && (
          <button
            type="button"
            className="btn rounded-lg border border-line/70 px-2.5 py-1 text-xs transition-colors hover:border-accent/60"
            onClick={() => {
              if (socket?.send("turn.pass", asSeat)) useGame.setState({ notice: "Пропускаем ход…" });
              else setSendError("Нет связи с сервером: пропустить ход не вышло.");
            }}
          >
            Пропустить ход
          </button>
        )}
        <div className="tf-composer-hints ml-auto hidden items-center gap-2 font-mono text-[11px] sm:flex">
          <span>
            <kbd className="rounded border border-line bg-raised px-1 py-0.5 text-[10px]">Enter</kbd> отправить
          </span>
          <span>
            <kbd className="rounded border border-line bg-raised px-1 py-0.5 text-[10px]">Shift+Enter</kbd> перенос
          </span>
          <span className="text-faint">|</span>
          <span>«речь»</span>
          <span>// вне игры</span>
        </div>
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

function D20Icon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polygon points="12 2 21.5 7.5 21.5 16.5 12 22 2.5 16.5 2.5 7.5 12 2" />
      <polygon points="12 6 18.5 16.5 5.5 16.5 12 6" />
      <line x1="12" y1="2" x2="12" y2="6" />
      <line x1="21.5" y1="7.5" x2="18.5" y2="16.5" />
      <line x1="2.5" y1="7.5" x2="5.5" y2="16.5" />
      <line x1="12" y1="22" x2="18.5" y2="16.5" />
      <line x1="12" y1="22" x2="5.5" y2="16.5" />
      <line x1="2.5" y1="7.5" x2="12" y2="6" />
      <line x1="21.5" y1="7.5" x2="12" y2="6" />
    </svg>
  );
}
