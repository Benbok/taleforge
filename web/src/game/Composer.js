import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useGame } from "../stores/game";
import { useDraft } from "./draft";
let counter = 0;
const clientId = () => `c${Date.now().toString(36)}${(counter++).toString(36)}`;
/** Секунд до конца хода; null — без таймера. */
export function secondsLeft(deadline, now) {
    if (!deadline)
        return null;
    return Math.max(0, Math.round(deadline - now / 1000));
}
/** Секунд до хода мастера по окну сбора реплик; null — окна нет или время неизвестно. */
export function waitLeft(createdAt, windowSec, now) {
    if (!createdAt || !windowSec)
        return null;
    return Math.max(0, Math.round((Date.parse(createdAt) + windowSec * 1000 - now) / 1000));
}
function useNow(active) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        if (!active)
            return;
        const t = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(t);
    }, [active]);
    return now;
}
/** Поле ввода — нативный чат: игрок пишет как есть, тип реплики определяет сервер. Отдельно только шёпот
 *  мастеру. Что можно сейчас, решает сервер (actions/blocked): закрытое не прячется молча — над полем причина. */
export default function Composer() {
    const { socket, connection, actions, blocked, turn, rejected, notice, snapshot, myPending, restored, clearRestored, addPending, clearRejected } = useGame();
    const { text, whisper, setText, setWhisper } = useDraft();
    const [sendError, setSendError] = useState(null);
    const can = (a) => actions.includes(a);
    const isMaster = snapshot?.me.role === "master";
    const mainAction = isMaster ? "chat.narrate" : "chat.play";
    const mainOpen = can(mainAction);
    const reason = blocked[mainAction] ?? null;
    const canWhisper = can("chat.whisper");
    const canOoc = can("chat.ooc");
    const myTurn = !!turn && !!snapshot?.me.seat_id && turn.seat_id === snapshot.me.seat_id;
    const now = useNow(!!turn?.deadline);
    const left = myTurn ? secondsLeft(turn?.deadline, now) : null;
    const nowWait = useNow(!!myPending);
    const wait = myPending ? waitLeft(myPending.created_at, snapshot?.collect_window_sec ?? 0, nowWait) : null;
    // отменённая реплика возвращается в поле, чтобы её поправить
    useEffect(() => {
        if (restored === null)
            return;
        if (!useDraft.getState().text)
            useDraft.getState().setText(restored);
        clearRestored();
    }, [restored, clearRestored]);
    // отклонённая реплика возвращается в поле, чтобы её можно было поправить
    useEffect(() => {
        if (rejected?.text && !useDraft.getState().text)
            useDraft.getState().setText(rejected.text);
    }, [rejected]);
    useEffect(() => {
        if (whisper && !canWhisper)
            setWhisper(false);
    }, [whisper, canWhisper, setWhisper]);
    if (!mainOpen && !canOoc && !canWhisper) {
        return (_jsx("div", { className: "border-t border-line bg-surface px-4 py-3 text-center text-muted", children: reason ?? "Вы смотрите кампанию: писать в чат могут только участники." }));
    }
    const trimmed = text.trim();
    const ooc = trimmed.startsWith("//");
    // что уйдёт при нажатии: так игрок заранее видит, дойдёт ли реплика
    const allowed = whisper ? canWhisper : ooc ? canOoc : mainOpen;
    const hint = whisper
        ? "Шёпот видит только мастер"
        : ooc
            ? "Вне игры: видят все, мастер не отвечает"
            : !mainOpen
                ? reason
                : null;
    function send(e) {
        e?.preventDefault();
        if (!trimmed)
            return;
        if (!allowed) {
            setSendError(hint ?? "Сейчас это отправить нельзя.");
            return;
        }
        if (connection !== "open" || !socket) {
            setSendError("Нет связи с сервером: текст сохранён, отправьте после переподключения.");
            return;
        }
        const id = clientId();
        const ok = socket.send("message.send", { kind: whisper ? "whisper" : "auto", text: trimmed, client_id: id });
        if (!ok) {
            setSendError("Нет связи с сервером: текст сохранён, отправьте после переподключения.");
            return;
        }
        addPending({ clientId: id, text: trimmed, whisper, at: Date.now() });
        setSendError(null);
        setText("");
    }
    function onKey(e) {
        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing)
            send(e);
    }
    const placeholder = whisper
        ? "Шёпот мастеру…"
        : mainOpen
            ? isMaster
                ? "Повествование…"
                : "Что делает ваш герой?"
            : "Только вне игры: начните с //";
    return (_jsxs("form", { onSubmit: send, className: "flex flex-col gap-2 border-t border-line bg-surface px-4 py-3", children: [myTurn && (_jsxs("p", { className: "tf-pop flex items-center gap-2 font-semibold text-accent", role: "status", children: ["\u0412\u0430\u0448 \u0445\u043E\u0434", turn?.round ? `, раунд ${turn.round}` : "", left !== null && _jsxs("span", { className: left <= 15 ? "text-warn" : "text-muted", children: ["\u00B7 \u043E\u0441\u0442\u0430\u043B\u043E\u0441\u044C ", left, " \u0441"] })] })), !myTurn && turn && !isMaster && (_jsxs("p", { className: "text-xs text-muted", children: ["\u0418\u0434\u0451\u0442 \u0431\u043E\u0439, \u0440\u0430\u0443\u043D\u0434 ", turn.round, ". \u0421\u0435\u0439\u0447\u0430\u0441 \u0445\u043E\u0434: ", turn.name, "."] })), rejected && (_jsxs("p", { role: "alert", className: "tf-pop flex items-start justify-between gap-2 rounded-md border border-bad px-3 py-2 text-bad", children: [_jsxs("span", { children: ["\u041D\u0435 \u043E\u0442\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u043E: ", rejected.reason] }), _jsx("button", { type: "button", className: "text-xs underline", onClick: clearRejected, children: "\u0441\u043A\u0440\u044B\u0442\u044C" })] })), notice && !rejected && _jsx("p", { className: "tf-pop text-xs text-muted", children: notice }), myPending && (_jsxs("p", { className: "text-xs text-muted", role: "status", children: ["\u041E\u0442\u0432\u0435\u0442 \u043C\u0430\u0441\u0442\u0435\u0440\u0430 \u2014 \u043A\u043E\u0433\u0434\u0430 \u043D\u0430\u043F\u0438\u0448\u0443\u0442 \u0432\u0441\u0435", wait ? ` или примерно через ${wait} с` : "", "."] })), (sendError || hint) && (_jsx("p", { role: sendError ? "alert" : undefined, className: `text-xs ${sendError || !allowed ? "text-warn" : "text-muted"}`, children: sendError ?? hint })), _jsxs("div", { className: "flex items-end gap-2", children: [_jsx("textarea", { id: "tf-composer", className: `field min-h-[2.75rem] flex-1 resize-none ${whisper ? "border-lore italic" : ""}`, rows: Math.min(6, Math.max(1, text.split("\n").length)), value: text, placeholder: placeholder, maxLength: 4000, onChange: (e) => {
                            setText(e.target.value);
                            if (sendError)
                                setSendError(null);
                            if (rejected)
                                clearRejected();
                        }, onKeyDown: onKey, "aria-label": "\u0421\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435" }), _jsx("button", { type: "submit", className: "btn btn-primary h-[2.75rem]", disabled: !trimmed, title: "\u041E\u0442\u043F\u0440\u0430\u0432\u0438\u0442\u044C (Enter)", children: "\u041E\u0442\u043F\u0440\u0430\u0432\u0438\u0442\u044C" })] }), _jsxs("div", { className: "flex flex-wrap items-center gap-3 text-xs text-muted", children: [canWhisper && (_jsxs("label", { className: "flex cursor-pointer items-center gap-1.5", children: [_jsx("input", { type: "checkbox", checked: whisper, onChange: (e) => setWhisper(e.target.checked) }), "\u0428\u0451\u043F\u043E\u0442 \u043C\u0430\u0441\u0442\u0435\u0440\u0443"] })), can("turn.pass") && (_jsx("button", { type: "button", className: "btn px-2 py-1 text-xs", onClick: () => {
                            if (socket?.send("turn.pass"))
                                useGame.setState({ notice: "Пропускаем ход…" });
                            else
                                setSendError("Нет связи с сервером: пропустить ход не вышло.");
                        }, children: "\u041F\u0440\u043E\u043F\u0443\u0441\u0442\u0438\u0442\u044C \u0445\u043E\u0434" })), _jsxs("span", { className: "ml-auto", children: ["\u0420\u0435\u0447\u044C \u2014 \u0432 \u043A\u0430\u0432\u044B\u0447\u043A\u0430\u0445, \u00AB//\u00BB \u2014 \u0432\u043D\u0435 \u0438\u0433\u0440\u044B", _jsx("span", { className: "hidden sm:inline", children: ". Enter \u2014 \u043E\u0442\u043F\u0440\u0430\u0432\u0438\u0442\u044C, Shift+Enter \u2014 \u043D\u043E\u0432\u0430\u044F \u0441\u0442\u0440\u043E\u043A\u0430" })] })] })] }));
}
