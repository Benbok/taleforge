import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import Avatar from "../components/Avatar";
import RichText from "./RichText";
import RollCardView from "./RollCardView";
import { useGame } from "../stores/game";
function heroName(m, who) {
    const hero = m.seat_id ? who.heroBySeat[m.seat_id] : undefined;
    return hero?.name ?? m.author ?? "Игрок";
}
const STATE_TEXT = { pending: "ждёт мастера", processing: "мастер отвечает", answered: "✓", failed: "не обработано" };
/** Статус реплики игрока: видят все, отменить может только автор, пока реплика ждёт хода. */
function ReplyStatus({ m, mine }) {
    const socket = useGame((s) => s.socket);
    if (!m.state)
        return null;
    return (_jsxs("p", { className: `mt-1 flex items-center gap-2 text-xs ${m.state === "failed" ? "text-warn" : "text-muted"}`, children: [_jsx("span", { children: STATE_TEXT[m.state] }), mine && m.state === "pending" && (_jsx("button", { type: "button", className: "underline", onClick: () => socket?.send("message.withdraw", { message_id: m.id }), children: "\u041E\u0442\u043C\u0435\u043D\u0438\u0442\u044C" }))] }));
}
/** Каждый тип сообщения выглядит по-своему: повествование, действие, речь, шёпот, вне игры, бросок, система. */
export default function MessageView({ m, who }) {
    if (m.kind === "roll" && m.data)
        return _jsx(RollCardView, { card: m.data });
    if (m.kind === "narration" && !m.whisper) {
        return (_jsx("div", { className: "tf-pop max-w-[70ch] whitespace-pre-line font-narration text-[18px] leading-relaxed", children: _jsx(RichText, { text: m.content }) }));
    }
    if (m.kind === "system") {
        return (_jsx("p", { className: "tf-pop mx-auto max-w-[60ch] rounded-lg border border-line px-3 py-1 text-center text-xs text-muted", children: m.content }));
    }
    if (m.kind === "ooc") {
        return (_jsxs("p", { className: "tf-pop text-xs text-muted", children: [_jsx("span", { className: "font-semibold", children: m.author ?? (m.seat_id ? who.seats[m.seat_id]?.user_name : null) ?? "участник" }) // {m.content.replace(/^\/\/\s*/, "")}
                , " // ", m.content.replace(/^\/\/\s*/, "")] }));
    }
    if (m.whisper) {
        const fromMaster = m.kind === "narration";
        return (_jsxs("div", { className: "tf-pop max-w-[70ch] rounded-lg border border-dashed border-line px-3 py-2", children: [_jsxs("p", { className: "mb-1 text-xs text-muted", children: [fromMaster ? "Шёпот мастера" : m.seat_id === who.mySeat ? "Ваш шёпот мастеру" : `Шёпот: ${heroName(m, who)}`, " \u00B7 \u0432\u0438\u0434\u0438\u0442\u0435 \u0442\u043E\u043B\u044C\u043A\u043E \u0432\u044B", fromMaster ? "" : " и мастер"] }), _jsx("p", { className: "font-narration", children: _jsx(RichText, { text: m.content }) }), !fromMaster && _jsx(ReplyStatus, { m: m, mine: m.seat_id === who.mySeat })] }));
    }
    const name = heroName(m, who);
    const mine = m.seat_id != null && m.seat_id === who.mySeat;
    return (_jsxs("div", { className: `tf-pop flex max-w-[70ch] gap-2 ${mine ? "ml-auto flex-row-reverse" : ""}`, children: [_jsx(Avatar, { name: name, role: "player", occupant: "human", presence: null, size: 28 }), _jsxs("div", { className: `rounded-lg px-3 py-2 ${mine ? "bg-raised" : "border border-line bg-surface"}`, children: [_jsx("p", { className: "text-xs text-muted", children: name }), m.kind === "speech" ? _jsxs("p", { children: ["\u00AB", m.content.replace(/^["«]|["»]$/g, ""), "\u00BB"] }) : _jsx("p", { className: "italic", children: m.content }), _jsx(ReplyStatus, { m: m, mine: mine })] })] }));
}
