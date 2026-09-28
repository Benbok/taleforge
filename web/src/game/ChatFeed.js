import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { parseMarkup } from "../lib/markup";
import { label } from "../lib/theme";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";
import MessageView from "./MessageView";
export const STAGES = {
    listening: "Мастер слушает…",
    remembering: "Мастер вспоминает…",
    rolling: "Мастер бросает кубики…",
    describing: "Мастер описывает…",
};
/** Лента: новые сообщения не сдвигают экран, если игрок читает старое, — вместо этого кнопка «Новые ↓». */
export default function ChatFeed({ campaignId }) {
    const { messages, pending, notes, seats, heroes, snapshot, masterStage, types, setTypes } = useGame();
    const theme = useSession((s) => s.theme);
    const [onlyStory, setOnlyStory] = useState(false);
    const [hideOoc, setHideOoc] = useState(false);
    const box = useRef(null);
    const [stuck, setStuck] = useState(true);
    const [unseen, setUnseen] = useState(0);
    const [now, setNow] = useState(() => Date.now());
    // долгая отправка: ИИ-мастер сначала разбирает реплику, игрок должен видеть, что она не потерялась
    useEffect(() => {
        if (!pending.length)
            return;
        const t = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(t);
    }, [pending.length]);
    const who = useMemo(() => {
        const heroBySeat = {};
        for (const h of Object.values(heroes))
            if (h.seat_id && (!heroBySeat[h.seat_id] || !h.dead))
                heroBySeat[h.seat_id] = h;
        return { seats: Object.fromEntries(seats.map((s) => [s.id, s])), heroBySeat, mySeat: snapshot?.me.seat_id ?? null };
    }, [heroes, seats, snapshot]);
    // цвет разметки до клика: тип сущностей спрашиваем пачкой (без имён и описаний)
    useEffect(() => {
        const ids = new Set();
        for (const m of messages)
            for (const p of parseMarkup(m.content))
                if ("id" in p && !types[p.id])
                    ids.add(p.id);
        if (!ids.size)
            return;
        api(`/api/campaigns/${campaignId}/entity-types?ids=${[...ids].slice(0, 100).join(",")}`)
            .then(setTypes)
            .catch(() => undefined);
    }, [messages, types, campaignId, setTypes]);
    const shown = messages.filter((m) => onlyStory ? m.kind === "narration" && !m.whisper : !(hideOoc && m.kind === "ooc"));
    const last = shown.at(-1)?.seq;
    useLayoutEffect(() => {
        const el = box.current;
        if (!el)
            return;
        if (stuck)
            el.scrollTop = el.scrollHeight;
        else
            setUnseen((n) => n + 1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [last, pending.length, notes.length, masterStage]);
    function onScroll() {
        const el = box.current;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        setStuck(atBottom);
        if (atBottom)
            setUnseen(0);
    }
    function toBottom() {
        const el = box.current;
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
        setUnseen(0);
        setStuck(true);
    }
    const notesAfter = (seq) => notes.filter((n) => n.afterSeq === seq);
    return (_jsxs("div", { className: "relative flex min-h-0 flex-1 flex-col", children: [_jsxs("div", { className: "flex items-center gap-3 border-b border-line px-4 py-1.5 text-xs text-muted", children: [_jsxs("label", { className: "flex cursor-pointer items-center gap-1.5", children: [_jsx("input", { type: "checkbox", checked: onlyStory, onChange: (e) => setOnlyStory(e.target.checked) }), "\u0422\u043E\u043B\u044C\u043A\u043E \u043F\u043E\u0432\u0435\u0441\u0442\u0432\u043E\u0432\u0430\u043D\u0438\u0435"] }), !onlyStory && (_jsxs("label", { className: "flex cursor-pointer items-center gap-1.5", children: [_jsx("input", { type: "checkbox", checked: hideOoc, onChange: (e) => setHideOoc(e.target.checked) }), "\u0421\u043A\u0440\u044B\u0442\u044C \u00AB\u0432\u043D\u0435 \u0438\u0433\u0440\u044B\u00BB"] }))] }), _jsxs("div", { ref: box, onScroll: onScroll, className: "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4", "aria-live": "polite", children: [shown.length === 0 && _jsx("p", { className: "m-auto text-muted", children: "\u0417\u0434\u0435\u0441\u044C \u043F\u043E\u044F\u0432\u0438\u0442\u0441\u044F \u0438\u0441\u0442\u043E\u0440\u0438\u044F. \u041C\u0430\u0441\u0442\u0435\u0440 \u043D\u0430\u0447\u043D\u0451\u0442, \u043A\u043E\u0433\u0434\u0430 \u0441\u0442\u0430\u0440\u0442\u0443\u0435\u0442 \u0441\u0435\u0441\u0441\u0438\u044F." }), shown.map((m) => (_jsxs("div", { className: "flex flex-col gap-2", children: [_jsx(MessageView, { m: m, who: who }), notesAfter(m.seq).map((n) => (_jsxs("p", { className: "tf-pop mx-auto rounded-full bg-raised px-3 py-1 text-xs", style: { color: "var(--tf-accent)" }, children: ["\u2726 ", n.text] }, n.id)))] }, m.id))), pending.map((p) => (_jsxs("div", { className: "ml-auto max-w-[70ch] rounded-lg bg-raised px-3 py-2 opacity-70", children: [_jsxs("p", { className: "flex items-center gap-2 text-xs text-muted", children: [_jsx(Spinner, {}), " ", now - p.at > 4000 ? "мастер разбирает реплику…" : "отправляется", p.whisper ? " · шёпот мастеру" : ""] }), _jsx("p", { children: p.text })] }, p.clientId))), masterStage && STAGES[masterStage] && (_jsxs("p", { className: "flex items-center gap-2 text-muted", role: "status", children: [_jsx(Spinner, {}), " ", label(theme, `master_status.${masterStage}`, STAGES[masterStage])] }))] }), !stuck && unseen > 0 && (_jsx("button", { className: "btn btn-primary absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 text-xs shadow-lg", onClick: toBottom, children: "\u041D\u043E\u0432\u044B\u0435 \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u044F \u2193" }))] }));
}
