import { useEffect, useState } from "react";
import type { RestChoice, RestVote } from "../lib/types";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";

const CHOICE_LABEL: Record<RestChoice, string> = {
  sleep: "Отдыхаю",
  watch: "На страже",
  no: "Против",
};
const CHOICE_DONE: Record<RestChoice, string> = {
  sleep: "отдыхает",
  watch: "на страже",
  no: "против",
};

/** Голосование группы за отдых: отдыхают только все вместе. Один «против» — отдыха нет; в ненадёжном месте каждый
 *  выбирает, спит он или стоит на страже (страж не отдыхает). Кто не ответил до конца срока — отдыхает со всеми. */
export default function RestVotePanel() {
  const votes = useGame((s) => s.restVotes);
  if (!votes.length) return null;
  return (
    <div className="flex flex-col">
      {votes.map((v) => (
        <RestCard key={v.vote_id} vote={v} />
      ))}
    </div>
  );
}

function RestCard({ vote }: { vote: RestVote }) {
  const socket = useGame((s) => s.socket);
  const mySeat = useGame((s) => s.snapshot?.me.seat_id ?? null);
  const standIn = useGame((s) => s.snapshot?.me.stand_in_for ?? []);
  const [sent, setSent] = useState<Record<string, { choice: RestChoice; at: number }>>({});
  const [dice, setDice] = useState<Record<string, string>>({});
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const left = Math.max(0, Math.ceil(vote.deadline - now / 1000));
  const mine = vote.heroes.filter((h) => h.voter && h.seat_id && (h.seat_id === mySeat || standIn.includes(h.seat_id)));
  const voters = vote.heroes.filter((h) => h.voter);
  const done = voters.filter((h) => h.choice).length;
  const danger = vote.safety !== "safe";

  function cast(heroId: string, choice: RestChoice) {
    const hd = dice[heroId] ?? "auto";
    const payload: Record<string, unknown> = {
      vote_id: vote.vote_id,
      character_id: heroId,
      choice,
    };
    if (vote.kind === "short" && choice === "sleep") payload.hit_dice = hd;
    if (!socket?.send("rest.ballot", payload)) {
      toast.error("Нет связи с сервером: выбор не отправлен.");
      return;
    }
    setSent((s) => ({ ...s, [heroId]: { choice, at: Date.now() } }));
  }

  return (
    <div role="group" aria-label="Голосование за отдых" className="tf-pop border-t-2 border-accent bg-raised px-4 py-3">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <p className="font-semibold">
          {vote.proposer ? `${vote.proposer} предлагает ` : "Отряд решает: "}
          {vote.kind_ru}
          {vote.place_name ? ` · ${vote.place_name}` : ""}
        </p>
        <span className={`shrink-0 tabular-nums text-sm ${left <= 20 ? "text-warn" : "text-muted"}`}>{left} с</span>
      </div>
      {vote.warning ? (
        <p className={`mb-2 text-sm ${vote.safety === "dangerous" ? "text-bad" : "text-warn"}`} role="alert">
          {vote.warning}
        </p>
      ) : (
        <p className="mb-2 text-xs text-muted">Место безопасное: засады не будет.</p>
      )}
      <p className="mb-2 text-xs text-muted">
        Отдыхают только все вместе: один «против» — отдыха нет.
        {danger
          ? " Страж не отдыхает; если на страже все, отдых никому не засчитают, а засада всё равно возможна."
          : ""}
        {" Кто не ответил до конца срока, отдыхает со всеми."}
      </p>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {vote.heroes.map((h) => (
          <li key={h.id}>
            {h.name}:{" "}
            <span className={h.choice ? "" : "text-muted"}>
              {!h.voter ? "без сознания, спит" : h.choice ? CHOICE_DONE[h.choice] : "решает…"}
            </span>
          </li>
        ))}
      </ul>
      {mine.map((h) => {
        const picked = h.choice ?? null;
        // ответ сервера обычно приходит сразу; отказ придёт сообщением с причиной, и кнопки снова свободны
        const mark = sent[h.id];
        const waiting = !!mark && mark.choice !== picked && now - mark.at < 5000;
        return (
          <div key={h.id} className="mb-2 flex flex-col gap-2">
            {mine.length > 1 && <p className="text-sm text-muted">За героя {h.name}:</p>}
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              {vote.choices.map((c) => (
                <button
                  key={c}
                  className={`btn flex-1 py-2 ${c === "no" ? "" : "btn-primary"} ${picked === c ? "ring-2 ring-accent" : ""}`}
                  onClick={() => cast(h.id, c)}
                  aria-pressed={picked === c}
                  disabled={waiting}
                >
                  {CHOICE_LABEL[c]}
                </button>
              ))}
            </div>
            {vote.kind === "short" && h.hit_dice_left > 0 && (
              <label className="flex items-center gap-2 text-sm text-muted">
                Кости хитов на лечение
                <select
                  className="input w-auto py-1"
                  value={dice[h.id] ?? "auto"}
                  onChange={(e) => setDice((d) => ({ ...d, [h.id]: e.target.value }))}
                >
                  <option value="auto">сколько нужно</option>
                  {Array.from({ length: h.hit_dice_left + 1 }, (_, i) => (
                    <option key={i} value={String(i)}>
                      {i}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <p className="text-xs text-muted" role="status">
              {waiting
                ? "Отправляем выбор…"
                : picked
                  ? "Выбор учтён. Можно передумать, пока решают остальные."
                  : "Выберите вариант."}
            </p>
          </div>
        );
      })}
      <p className="text-xs text-muted">
        Решили: {done} из {voters.length}.
      </p>
    </div>
  );
}
