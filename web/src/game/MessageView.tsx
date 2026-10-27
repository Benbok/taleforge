import type { ChatMessage, HeroPublic, SeatState } from "../lib/types";
import Avatar from "../components/Avatar";
import RichText from "./RichText";
import RollCardView from "./RollCardView";
import VoiceClip from "./VoiceClip";
import { useGame } from "../stores/game";

export interface Who {
  seats: Record<string, SeatState>;
  heroBySeat: Record<string, HeroPublic>;
  mySeat: string | null;
}

function heroName(m: ChatMessage, who: Who): string {
  const hero = m.seat_id ? who.heroBySeat[m.seat_id] : undefined;
  return hero?.name ?? m.author ?? "Игрок";
}

const STATE_TEXT = { pending: "ждёт мастера", processing: "мастер отвечает", answered: "✓", failed: "не обработано" } as const;

/** Статус реплики игрока: видят все; отменить ожидающую или повторить необработанную может только автор. */
function ReplyStatus({ m, mine }: { m: ChatMessage; mine: boolean }) {
  const socket = useGame((s) => s.socket);
  if (!m.state) return null;
  const failure = m.data?.action_failure;
  if (m.state === "answered" && failure) {
    return <p className="mt-1 text-xs text-warn" role="status">
      {failure.message}
    </p>;
  }
  return (
    <p className={`mt-1 flex items-center gap-2 text-xs ${m.state === "failed" ? "text-warn" : "text-muted"}`}>
      <span>{m.state === "failed" && failure ? failure.message : STATE_TEXT[m.state]}</span>
      {mine && m.state === "pending" && (
        <button type="button" className="underline" onClick={() => socket?.send("message.withdraw", { message_id: m.id })}>
          Отменить
        </button>
      )}
      {mine && m.state === "failed" && (
        // Сервер восстанавливает тот же ход по сохранённым решениям и квитанциям.
        <button
          type="button"
          className="rounded border border-warn/50 px-2 py-0.5 font-medium hover:bg-warn/10"
          onClick={() => socket?.send("message.retry", { message_id: m.id })}
        >
          Повторить
        </button>
      )}
    </p>
  );
}

/** Каждый тип сообщения выглядит по-своему: повествование, действие, речь, шёпот, вне игры, бросок, система. */
export default function MessageView({ m, who }: { m: ChatMessage; who: Who }) {
  if (m.kind === "roll" && m.data) return <RollCardView card={m.data} />;
  if (m.kind === "narration" && (!m.whisper || m.scope === 'party')) {
    return (
      <div
        className={`tf-pop tf-narration-card w-full min-w-0 rounded-xl border border-line-soft/80 border-l-[3px] border-l-accent/90 bg-surface-2/45 p-3.5 sm:p-4.5 shadow-2xs transition-colors ${
          m.scope === "party" ? "tf-narration-party" : ""
        }`}
      >
        <div className="tf-narration-header flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-line-soft/40">
          <div className="flex items-center gap-1.5 font-heading text-xs font-semibold uppercase tracking-wider text-accent">
            <span aria-hidden="true" className="text-xs">🖋️</span>
            <span>Мастер</span>
            {m.scope === "party" && (
              <span className="font-mono text-[10px] text-patina lowercase">· для группы</span>
            )}
          </div>
          {(m.data?.voice || m.data?.voice_parts) && (
            <VoiceClip
              clips={m.data.voices ?? (m.data.voice ? [m.data.voice] : [])}
              expected={m.data.voice_parts}
              autoPlay={m.fresh}
            />
          )}
        </div>
        <div className="tf-narration-text break-words whitespace-pre-line font-narration text-[19px] leading-[1.65] sm:text-[21px] text-ink">
          <RichText text={m.content} />
        </div>
      </div>
    );
  }
  if (m.kind === "system") {
    return (
      <p className="tf-pop mx-auto max-w-[65ch] rounded-lg border border-line px-3 py-1.5 text-center text-xs text-muted">
        {m.content}
      </p>
    );
  }
  if (m.kind === "ooc") {
    return (
      <p className="tf-pop text-xs text-muted max-w-[76ch]">
        <span className="font-semibold text-ink">{m.author ?? (m.seat_id ? who.seats[m.seat_id]?.user_name : null) ?? "участник"}</span> // {m.content.replace(/^\/\/\s*/, "")}
      </p>
    );
  }
  if (m.whisper) {
    const fromMaster = m.kind === "narration";
    return (
      <div className="tf-pop tf-whisper-box max-w-[76ch] rounded-[10px] border border-dashed border-accent/40 bg-surface/80 p-3 sm:p-4">
        <p className="mb-1.5 text-xs text-muted">
          {fromMaster ? (m.data?.whisper_reply ? "Мастер отвечает на ваш шёпот" : "Шёпот мастера") : m.seat_id === who.mySeat ? "Ваш шёпот мастеру" : `Шёпот: ${heroName(m, who)}`} ·
          видите только вы{fromMaster ? "" : " и мастер"}
        </p>
        {m.data?.voice && (
          <VoiceClip clips={[m.data.voice]} autoPlay={m.fresh && fromMaster} caption={fromMaster ? undefined : "Голосовое сообщение"} />
        )}
        <p className="tf-message-body font-narration text-[16px] leading-relaxed text-ink">
          <RichText text={m.content} />
        </p>
        {!fromMaster && <ReplyStatus m={m} mine={m.seat_id === who.mySeat} />}
      </div>
    );
  }
  const name = heroName(m, who);
  const mine = m.seat_id != null && m.seat_id === who.mySeat;
  const ai = !!m.data?.ai; // говорит ИИ-игрок или ИИ за ушедшего игрока
  return (
    <div className={`tf-pop flex max-w-[76ch] gap-3 ${mine ? "ml-auto" : ""}`}>
      <div className="shrink-0 pt-0.5 tf-message-avatar">
        <Avatar name={name} portraitUrl={m.seat_id ? who.heroBySeat[m.seat_id]?.portrait_url : null} role="player" occupant={ai ? "agent" : "human"} presence={null} size={32} />
      </div>
      <div
        className={`tf-message-bubble min-w-0 flex-1 rounded-[12px] p-3 sm:p-3.5 transition-colors ${
          mine
            ? "border border-accent/40 bg-raised/90 shadow-xs ring-1 ring-accent/15"
            : "border border-line/80 bg-surface shadow-xs"
        }`}
      >
        <div className="tf-message-header flex items-center gap-2 mb-1.5">
          <span className="font-heading font-semibold text-sm text-ink">{name}</span>
          {mine && <span className="font-mono text-[10px] text-accent uppercase tracking-wider font-semibold">(вы)</span>}
          {ai && <span className="font-mono text-[10px] text-muted" title="Реплику написал ИИ">· ИИ</span>}
        </div>
        {m.data?.voice && <VoiceClip clips={[m.data.voice]} caption="Голосовое сообщение" />}
        {m.kind === "speech" ? (
          <p className="tf-message-body font-narration text-[16px] sm:text-[17px] leading-[1.6] text-ink italic">
            «{m.content.replace(/^["«]|["»]$/g, "")}»
          </p>
        ) : (
          <p className="tf-message-body font-narration text-[15px] sm:text-[16px] leading-[1.6] text-ink-2 whitespace-pre-line">
            {m.content}
          </p>
        )}
        <ReplyStatus m={m} mine={mine} />
      </div>
    </div>
  );
}
