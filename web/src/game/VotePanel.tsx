import { useEffect, useState } from "react";
import type { Vote } from "../lib/types";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";

/** Голосование, когда кто-то ушёл из сети во время сессии (ТЗ, раздел 11). Голосуют игроки, которые были в сети
 *  при его начале; остальные видят, что идёт голосование и сколько осталось. Нет большинства за 2 минуты — пауза. */
export default function VotePanel() {
  const votes = useGame((s) => s.votes);
  if (!votes.length) return null;
  return (
    <div className="flex flex-col">
      {votes.map((v) => (
        <VoteCard key={v.vote_id} vote={v} />
      ))}
    </div>
  );
}

export function voteQuestion(v: Pick<Vote, "subject" | "who" | "hero">): string {
  return v.subject === "master"
    ? `Мастер (${v.who}) вне сети. Как продолжить?`
    : `${v.who} вне сети. Что делать с героем ${v.hero ?? ""}?`.replace(" ?", "?");
}

function VoteCard({ vote }: { vote: Vote }) {
  const socket = useGame((s) => s.socket);
  const me = useGame((s) => s.snapshot?.me.seat_id ?? null);
  const [sent, setSent] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const left = Math.max(0, Math.ceil(vote.deadline - now / 1000));
  const voter = !!me && vote.voters.includes(me);
  const voted = !!me && vote.voted.includes(me);
  const need = Math.floor(vote.voters.length / 2) + 1;

  function cast(option: string) {
    if (!socket?.send("vote.cast", { vote_id: vote.vote_id, option })) {
      toast.error("Нет связи с сервером: голос не отправлен.");
      return;
    }
    setSent(option);
  }

  return (
    <div role="group" aria-label="Голосование" className="tf-pop border-t-2 border-warn bg-raised px-4 py-3">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <p className="font-semibold">{voteQuestion(vote)}</p>
        <span className={`shrink-0 tabular-nums text-sm ${left <= 20 ? "text-warn" : "text-muted"}`}>{left} с</span>
      </div>
      <p className="mb-2 text-xs text-muted">
        Решает большинство: нужно {need} из {vote.voters.length}. Ничья или время вышло — пауза. Вернётся — голосование
        отменится.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {vote.options.map((o) => {
          const n = vote.tally[o.id] ?? 0;
          const mine = sent === o.id;
          return voter ? (
            <button
              key={o.id}
              className={`btn flex-1 justify-between py-2 ${o.id === "pause" ? "" : "btn-primary"} ${mine ? "ring-2 ring-accent" : ""}`}
              onClick={() => cast(o.id)}
              aria-pressed={mine}
            >
              <span>{o.label}</span>
              <span className="tabular-nums opacity-80">{n}</span>
            </button>
          ) : (
            <span key={o.id} className="flex flex-1 justify-between rounded-md border border-line px-3 py-2 text-sm">
              <span>{o.label}</span>
              <span className="tabular-nums text-muted">{n}</span>
            </span>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted" role="status">
        {voter
          ? voted
            ? "Ваш голос учтён. Можно передумать, пока голосование идёт."
            : sent
              ? "Отправляем голос…"
              : "Выберите вариант."
          : "Голосуют игроки, которые были в сети, когда оно началось."}
        {` Проголосовали: ${vote.voted.length} из ${vote.voters.length}.`}
      </p>
    </div>
  );
}
