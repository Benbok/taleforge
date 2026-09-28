import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { parseMarkup } from "../lib/markup";
import { label } from "../lib/theme";
import type { EntityType, HeroPublic } from "../lib/types";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";
import MessageView, { type Who } from "./MessageView";

export const STAGES: Record<string, string> = {
  listening: "Мастер слушает…",
  remembering: "Мастер вспоминает…",
  rolling: "Мастер бросает кубики…",
  describing: "Мастер описывает…",
};

/** Лента: новые сообщения не сдвигают экран, если игрок читает старое, — вместо этого кнопка «Новые ↓». */
export default function ChatFeed({ campaignId }: { campaignId: string }) {
  const { messages, pending, notes, seats, heroes, snapshot, masterStage, types, setTypes } = useGame();
  const theme = useSession((s) => s.theme);
  const [onlyStory, setOnlyStory] = useState(false);
  const [hideOoc, setHideOoc] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const [stuck, setStuck] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  // долгая отправка: ИИ-мастер сначала разбирает реплику, игрок должен видеть, что она не потерялась
  useEffect(() => {
    if (!pending.length) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [pending.length]);

  const who: Who = useMemo(() => {
    const heroBySeat: Record<string, HeroPublic> = {};
    for (const h of Object.values(heroes)) if (h.seat_id && (!heroBySeat[h.seat_id] || !h.dead)) heroBySeat[h.seat_id] = h;
    return { seats: Object.fromEntries(seats.map((s) => [s.id, s])), heroBySeat, mySeat: snapshot?.me.seat_id ?? null };
  }, [heroes, seats, snapshot]);

  // цвет разметки до клика: тип сущностей спрашиваем пачкой (без имён и описаний)
  useEffect(() => {
    const ids = new Set<string>();
    for (const m of messages) for (const p of parseMarkup(m.content)) if ("id" in p && !types[p.id]) ids.add(p.id);
    if (!ids.size) return;
    api<Record<string, EntityType>>(`/api/campaigns/${campaignId}/entity-types?ids=${[...ids].slice(0, 100).join(",")}`)
      .then(setTypes)
      .catch(() => undefined);
  }, [messages, types, campaignId, setTypes]);

  const shown = messages.filter((m) =>
    onlyStory ? m.kind === "narration" && !m.whisper : !(hideOoc && m.kind === "ooc"),
  );
  const last = shown.at(-1)?.seq;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    if (stuck) el.scrollTop = el.scrollHeight;
    else setUnseen((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last, pending.length, notes.length, masterStage]);

  function onScroll() {
    const el = box.current!;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setStuck(atBottom);
    if (atBottom) setUnseen(0);
  }

  function toBottom() {
    const el = box.current!;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setUnseen(0);
    setStuck(true);
  }

  const notesAfter = (seq: number) => notes.filter((n) => n.afterSeq === seq);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-line px-4 py-1.5 text-xs text-muted">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" checked={onlyStory} onChange={(e) => setOnlyStory(e.target.checked)} />
          Только повествование
        </label>
        {!onlyStory && (
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={hideOoc} onChange={(e) => setHideOoc(e.target.checked)} />
            Скрыть «вне игры»
          </label>
        )}
      </div>
      <div ref={box} onScroll={onScroll} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4" aria-live="polite">
        {shown.length === 0 && <p className="m-auto text-muted">Здесь появится история. Мастер начнёт, когда стартует сессия.</p>}
        {shown.map((m) => (
          <div key={m.id} className="flex flex-col gap-2">
            <MessageView m={m} who={who} />
            {notesAfter(m.seq).map((n) => (
              <p key={n.id} className="tf-pop mx-auto rounded-full bg-raised px-3 py-1 text-xs" style={{ color: "var(--tf-accent)" }}>
                ✦ {n.text}
              </p>
            ))}
          </div>
        ))}
        {pending.map((p) => (
          <div key={p.clientId} className="ml-auto max-w-[70ch] rounded-lg bg-raised px-3 py-2 opacity-70">
            <p className="flex items-center gap-2 text-xs text-muted">
              <Spinner /> {now - p.at > 4000 ? "мастер разбирает реплику…" : "отправляется"}
              {p.whisper ? " · шёпот мастеру" : ""}
            </p>
            <p>{p.text}</p>
          </div>
        ))}
        {masterStage && STAGES[masterStage] && (
          <p className="flex items-center gap-2 text-muted" role="status">
            <Spinner /> {label(theme, `master_status.${masterStage}`, STAGES[masterStage])}
          </p>
        )}
      </div>
      {!stuck && unseen > 0 && (
        <button className="btn btn-primary absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 text-xs shadow-lg" onClick={toBottom}>
          Новые сообщения ↓
        </button>
      )}
    </div>
  );
}
