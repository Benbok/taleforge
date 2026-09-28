import type { ChatMessage, HeroPublic, SeatState } from "../lib/types";
import Avatar from "../components/Avatar";
import RichText from "./RichText";
import RollCardView from "./RollCardView";

export interface Who {
  seats: Record<string, SeatState>;
  heroBySeat: Record<string, HeroPublic>;
  mySeat: string | null;
}

function heroName(m: ChatMessage, who: Who): string {
  const hero = m.seat_id ? who.heroBySeat[m.seat_id] : undefined;
  return hero?.name ?? m.author ?? "Игрок";
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
      </div>
    </div>
  );
}
