import type { ChatMessage, HeroPublic, SeatState } from "../lib/types";
import Avatar from "../components/Avatar";
import RichText from "./RichText";
import RollCardView from "./RollCardView";
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

/** Статус реплики игрока: видят все, отменить может только автор, пока реплика ждёт хода. */
function ReplyStatus({ m, mine }: { m: ChatMessage; mine: boolean }) {
  const socket = useGame((s) => s.socket);
  if (!m.state) return null;
  return (
    <p className={`mt-1 flex items-center gap-2 text-xs ${m.state === "failed" ? "text-warn" : "text-muted"}`}>
      <span>{STATE_TEXT[m.state]}</span>
      {mine && m.state === "pending" && (
        <button type="button" className="underline" onClick={() => socket?.send("message.withdraw", { message_id: m.id })}>
          Отменить
        </button>
      )}
    </p>
  );
}

/** Каждый тип сообщения выглядит по-своему: повествование, действие, речь, шёпот, вне игры, бросок, система. */
export default function MessageView({ m, who }: { m: ChatMessage; who: Who }) {
  if (m.kind === "roll" && m.data) return <RollCardView card={m.data} />;
  if (m.kind === "narration" && !m.whisper) {
    return (
      <div className="tf-pop max-w-[70ch] whitespace-pre-line font-narration text-[18px] leading-relaxed">
        <RichText text={m.content} />
      </div>
    );
  }
  if (m.kind === "system") {
    return (
      <p className="tf-pop mx-auto max-w-[60ch] rounded-lg border border-line px-3 py-1 text-center text-xs text-muted">
        {m.content}
      </p>
    );
  }
  if (m.kind === "ooc") {
    return (
      <p className="tf-pop text-xs text-muted">
        <span className="font-semibold">{m.author ?? (m.seat_id ? who.seats[m.seat_id]?.user_name : null) ?? "участник"}</span> // {m.content.replace(/^\/\/\s*/, "")}
      </p>
    );
  }
  if (m.whisper) {
    const fromMaster = m.kind === "narration";
    return (
      <div className="tf-pop max-w-[70ch] rounded-lg border border-dashed border-line px-3 py-2">
        <p className="mb-1 text-xs text-muted">
          {fromMaster ? "Шёпот мастера" : m.seat_id === who.mySeat ? "Ваш шёпот мастеру" : `Шёпот: ${heroName(m, who)}`} ·
          видите только вы{fromMaster ? "" : " и мастер"}
        </p>
        <p className="font-narration">
          <RichText text={m.content} />
        </p>
        {!fromMaster && <ReplyStatus m={m} mine={m.seat_id === who.mySeat} />}
      </div>
    );
  }
  const name = heroName(m, who);
  const mine = m.seat_id != null && m.seat_id === who.mySeat;
  return (
    <div className={`tf-pop flex max-w-[70ch] gap-2 ${mine ? "ml-auto flex-row-reverse" : ""}`}>
      <Avatar name={name} role="player" occupant="human" presence={null} size={28} />
      <div className={`rounded-lg px-3 py-2 ${mine ? "bg-raised" : "border border-line bg-surface"}`}>
        <p className="text-xs text-muted">{name}</p>
        {m.kind === "speech" ? <p>«{m.content.replace(/^["«]|["»]$/g, "")}»</p> : <p className="italic">{m.content}</p>}
        <ReplyStatus m={m} mine={mine} />
      </div>
    </div>
  );
}
