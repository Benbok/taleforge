import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { parseMarkup } from "../lib/markup";
import { label } from "../lib/theme";
import type { EntityType, HeroPublic } from "../lib/types";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";
import MessageView, { type Who } from "./MessageView";
import ChronicleDivider from "./ChronicleDivider";
import { chronicleEntries } from "./chronicle";
import { STAGES } from "./masterStatus";

export { STAGES } from "./masterStatus";

/** Лента: новые сообщения не сдвигают экран, если игрок читает старое, — вместо этого кнопка «Новые ↓». */
export default function ChatFeed({ campaignId }: { campaignId: string }) {
  const { messages, pending, notes, seats, heroes, snapshot, masterStage, types, setTypes } = useGame();
  const [onlyStory, setOnlyStory] = useState(false);
  const [hideOoc, setHideOoc] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
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

  const shown = chronicleEntries(messages, { onlyStory, hideOoc });
  const last = shown.at(-1)?.message.seq;

  const scrollToBottom = (smooth = false) => {
    const el = box.current;
    if (!el) return;
    if (smooth) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  };

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    if (stuck || masterStage) {
      scrollToBottom();
      const raf = requestAnimationFrame(() => scrollToBottom());
      const timer = setTimeout(() => scrollToBottom(), 80);
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(timer);
      };
    } else {
      setUnseen((n) => n + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last, pending.length, notes.length, masterStage]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (stuck || masterStage) {
        el.scrollTop = el.scrollHeight;
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [stuck, masterStage]);

  function onScroll() {
    const el = box.current!;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setStuck(atBottom);
    if (atBottom) setUnseen(0);
  }

  function toBottom() {
    scrollToBottom(true);
    setUnseen(0);
    setStuck(true);
  }

  const notesAfter = (seq: number) => notes.filter((n) => n.afterSeq === seq);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line/60 bg-surface/50 px-3 py-2 sm:px-4 text-xs">
        <button
          type="button"
          role="checkbox"
          aria-checked={onlyStory}
          onClick={() => setOnlyStory(!onlyStory)}
          className={`inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition cursor-pointer select-none ${
            onlyStory
              ? "border border-accent/70 bg-accent/15 text-accent shadow-xs"
              : "border border-line/80 bg-raised/70 text-muted hover:border-accent/40 hover:text-ink"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full transition-all ${
              onlyStory ? "bg-accent shadow-[0_0_6px_var(--tf-accent)]" : "bg-muted/40"
            }`}
          />
          Только повествование
        </button>
        {!onlyStory && (
          <button
            type="button"
            role="checkbox"
            aria-checked={hideOoc}
            onClick={() => setHideOoc(!hideOoc)}
            className={`inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition cursor-pointer select-none ${
              hideOoc
                ? "border border-accent/70 bg-accent/15 text-accent shadow-xs"
                : "border border-line/80 bg-raised/70 text-muted hover:border-accent/40 hover:text-ink"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full transition-all ${
                hideOoc ? "bg-accent shadow-[0_0_6px_var(--tf-accent)]" : "bg-muted/40"
              }`}
            />
            Скрыть «вне игры»
          </button>
        )}
      </div>
      <div ref={box} onScroll={onScroll} className="tf-story-feed flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-5 sm:px-6" aria-live="polite">
        {shown.length === 0 && <p className="m-auto text-muted">Здесь появится история. Мастер начнёт, когда стартует сессия.</p>}
        {shown.map(({ message, divider }) => (
          <div key={message.id} className="flex flex-col gap-2">
            {divider && <ChronicleDivider message={message} />}
            <MessageView m={message} who={who} />
            {notesAfter(message.seq).map((n) => (
              <p key={n.id} className="tf-pop mx-auto rounded-full bg-raised px-3 py-1 text-xs" style={{ color: "var(--tf-accent)" }}>
                ✦ {n.text}
              </p>
            ))}
          </div>
        ))}
        {pending.map((p) => (
          <div key={p.clientId} className="ml-auto max-w-[65ch] rounded-lg bg-raised px-3 py-2">
            <p className="flex items-center gap-2 text-xs text-muted">
              <Spinner />{" "}
              {p.voice ? "голосовое · расшифровываю…" : now - p.at > 4000 ? "мастер разбирает реплику…" : "отправляется"}
              {p.whisper ? " · шёпот мастеру" : ""}
            </p>
            {p.text && <p>{p.text}</p>}
          </div>
        ))}
        {masterStage && STAGES[masterStage] && (
          <MasterThinkingCard stage={masterStage} />
        )}
        <div ref={bottomRef} className="h-8 shrink-0" aria-hidden="true" />
      </div>
      {!stuck && unseen > 0 && (
        <button className="btn btn-primary absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 text-xs shadow-lg" onClick={toBottom}>
          Новые сообщения ↓
        </button>
      )}
    </div>
  );
}

/** Атмосферный индикатор размышления и подготовки ответа мастера */
function MasterThinkingCard({ stage }: { stage: string }) {
  const cardRef = useRef<HTMLDivElement>(null);
  const theme = useSession((s) => s.theme);
  const text = label(theme, `master_status.${stage}`, STAGES[stage] ?? "Мастер обдумывает ответ…");

  useEffect(() => {
    cardRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [stage]);

  return (
    <div
      ref={cardRef}
      className="tf-pop tf-master-thinking my-2 flex max-w-[72ch] shrink-0 flex-col gap-2.5 rounded-xl border p-3.5 shadow-xs sm:p-4"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* Аватар мастера с мягкой аурой и динамической иконкой этапа */}
          <div className="tf-master-aura flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-accent/50 bg-accent/10 shadow-xs">
            <MasterStageIcon stage={stage} />
          </div>
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-heading text-xs font-bold tracking-wide text-ink">Мастер</span>
            <span className="font-mono text-xs text-accent">· {text}</span>
          </div>
        </div>

        {/* Пульсирующие руны ожидания */}
        <div className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-accent/80" aria-hidden="true">
          <span className="tf-runic-dot delay-0">✦</span>
          <span className="tf-runic-dot delay-150">✦</span>
          <span className="tf-runic-dot delay-300">✦</span>
        </div>
      </div>

      {/* Призрачные мерцающие строки текста (эффект материализации повествования) */}
      <div className="flex flex-col gap-2 pt-1" aria-hidden="true">
        <div className="tf-shimmer-line h-2 w-11/12 rounded-full opacity-60" />
        <div className="tf-shimmer-line h-2 w-4/5 rounded-full opacity-45" />
        <div className="tf-shimmer-line h-2 w-3/5 rounded-full opacity-30" />
      </div>
    </div>
  );
}

function MasterStageIcon({ stage }: { stage: string }) {
  switch (stage) {
    case "rolling":
      return (
        <svg
          className="tf-anim-rolling h-3.5 w-3.5 text-accent"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polygon points="12 2 21.5 7.5 21.5 16.5 12 22 2.5 16.5 2.5 7.5 12 2" />
          <polygon points="12 6 18.5 16.5 5.5 16.5 12 6" />
        </svg>
      );
    case "describing":
      return (
        <svg
          className="tf-anim-writing h-3.5 w-3.5 text-accent"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z" />
          <line x1="16" y1="8" x2="2" y2="22" />
        </svg>
      );
    case "remembering":
      return (
        <svg
          className="tf-anim-rune h-3.5 w-3.5 text-accent"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
      );
    case "listening":
      return (
        <svg
          className="h-3.5 w-3.5 animate-pulse text-accent"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
          <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
        </svg>
      );
    default:
      return <span className="font-mono text-xs text-accent">✦</span>;
  }
}
