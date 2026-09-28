import { jsxs as _jsxs, jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
import { useGame } from "../stores/game";
import { Spinner } from "../components/ActionButton";
import { useDraft } from "./draft";
import { cardActions, TYPE_COLOR, TYPE_ICON, TYPE_NAME } from "./entities";
import { useInspector } from "./inspector";
import { attack } from "./quick";
import { signed } from "./hero";
import { toast } from "../stores/toasts";
const STAT_NAMES = { ac: "КБ", hp: "Хиты", hp_max: "из", speed: "Скорость" };
/** Карточка знаний рядом со словом (на телефоне — снизу во всю ширину). Показывает только открытое герою,
 *  закрытые уровни — строкой «ещё можно узнать». Действие подставляет текст в поле ввода, отправляет игрок. */
export default function EntityPopover() {
    const { id, label, anchor, close } = useInspector();
    const card = useGame((s) => (id ? s.cards[id] : undefined));
    const insert = useDraft((s) => s.insert);
    const ref = useRef(null);
    useEffect(() => {
        if (!id)
            return;
        const onKey = (e) => e.key === "Escape" && close();
        const onDown = (e) => ref.current && !ref.current.contains(e.target) && close();
        window.addEventListener("keydown", onKey);
        window.addEventListener("mousedown", onDown);
        return () => {
            window.removeEventListener("keydown", onKey);
            window.removeEventListener("mousedown", onDown);
        };
    }, [id, close]);
    if (!id)
        return null;
    const phone = window.innerWidth < 768;
    const style = anchor && !phone
        ? {
            left: Math.min(Math.max(8, anchor.left), window.innerWidth - 336),
            top: anchor.bottom + 8 + 320 > window.innerHeight ? Math.max(8, anchor.top - 328) : anchor.bottom + 8,
        }
        : undefined;
    const name = card?.name ?? label;
    const type = card?.type;
    return (_jsxs("div", { ref: ref, role: "dialog", "aria-label": `Карточка: ${name}`, className: `tf-pop fixed z-40 max-h-[70dvh] overflow-y-auto border border-line bg-raised p-4 shadow-xl ${style ? "w-80 rounded-lg" : "inset-x-0 bottom-0 rounded-t-xl"}`, style: style, children: [_jsxs("div", { className: "mb-2 flex items-start justify-between gap-2", children: [_jsxs("div", { children: [_jsxs("p", { className: "text-xs uppercase tracking-wide", style: { color: type ? TYPE_COLOR[type] : undefined }, children: [type ? `${TYPE_ICON[type]} ${TYPE_NAME[type]}` : "Карточка", card?.level_name ? ` · ${card.level_name}` : ""] }), _jsx("h3", { className: "text-lg font-semibold", children: name })] }), _jsx("button", { className: "text-muted hover:text-ink", onClick: close, "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C", children: "\u00D7" })] }), !card && (_jsxs("p", { className: "flex items-center gap-2 text-muted", children: [_jsx(Spinner, {}), " \u0412\u0441\u043F\u043E\u043C\u0438\u043D\u0430\u0435\u043C, \u0447\u0442\u043E \u0432\u044B \u0437\u043D\u0430\u0435\u0442\u0435\u2026"] })), card?.error && _jsx("p", { className: "text-bad", children: card.error }), card?.hero && (_jsxs("div", { className: "flex flex-col gap-2", children: [_jsxs("p", { className: "text-muted", children: [[card.hero.origin_name, card.hero.class_name, `${card.hero.level} уровень`].filter(Boolean).join(" · "), card.hero.dead ? " · погиб" : ""] }), card.hero.public_bio && _jsx("p", { className: "font-narration", children: card.hero.public_bio }), card.hero.bonds && card.hero.bonds.length > 0 && (_jsx(Section, { title: "\u0418\u0437\u0432\u0435\u0441\u0442\u043D\u043E \u043E\u0442\u0440\u044F\u0434\u0443", children: card.hero.bonds.map((b) => (_jsxs("li", { children: [_jsxs("span", { className: "text-muted", children: [b.question, " "] }), b.answer] }, b.question))) })), _jsx(Learned, { facts: card.facts, heard: card.heard })] })), card && !card.error && !card.hero && (_jsxs("div", { className: "flex flex-col gap-2", children: [card.kind_name && card.kind_name !== name && _jsx("p", { className: "text-muted", children: card.kind_name }), card.description && _jsx("p", { className: "font-narration", children: card.description }), card.lore && _jsx("p", { className: "font-narration text-muted", children: card.lore }), card.habits && _jsxs("p", { children: ["\u041F\u043E\u0432\u0430\u0434\u043A\u0438: ", card.habits] }), card.condition && _jsxs("p", { children: ["\u0421\u043E\u0441\u0442\u043E\u044F\u043D\u0438\u0435: ", card.condition] }), card.attacks && card.attacks.length > 0 && _jsxs("p", { children: ["\u041E\u0440\u0443\u0436\u0438\u0435: ", card.attacks.join(", ")] }), card.vulnerable && _jsxs("p", { children: ["\u0423\u044F\u0437\u0432\u0438\u043C: ", card.vulnerable.join(", ")] }), card.stats && (_jsx("p", { className: "text-xs", children: Object.entries(card.stats)
                            .filter(([k, v]) => v != null && typeof v !== "object" && STAT_NAMES[k])
                            .map(([k, v]) => `${STAT_NAMES[k]} ${v}`)
                            .join(" · ") })), _jsx(Learned, { facts: card.facts, heard: card.heard }), card.locked && card.locked.length > 0 && (_jsxs("p", { className: "text-xs text-muted", children: ["\u0421\u043A\u0440\u044B\u0442\u043E: \u0435\u0449\u0451 \u043C\u043E\u0436\u043D\u043E \u0443\u0437\u043D\u0430\u0442\u044C (", card.locked.join(", "), ")"] })), type === "creature" && _jsx(QuickAttack, { id: id, name: name, onDone: close }), _jsx("div", { className: "mt-1 flex flex-wrap gap-2", children: cardActions(type, name).map((a) => (_jsx("button", { className: "btn px-2 py-1 text-xs", onClick: () => {
                                insert(a.text);
                                close();
                            }, children: a.label }, a.label))) })] }))] }));
}
function Section({ title, children }) {
    return (_jsxs("div", { children: [_jsx("p", { className: "mb-1 text-xs uppercase tracking-wide text-muted", children: title }), _jsx("ul", { className: "flex list-none flex-col gap-1 p-0", children: children })] }));
}
/** Что именно этот герой узнал в игре: факты от мастера и фразы из рассказа, которые видел этот игрок. */
function Learned({ facts, heard }) {
    return (_jsxs(_Fragment, { children: [facts && facts.length > 0 && (_jsx(Section, { title: "\u0412\u044B \u0437\u043D\u0430\u0435\u0442\u0435", children: facts.map((f) => (_jsxs("li", { children: ["\u2022 ", f] }, f))) })), heard && heard.length > 0 && (_jsx(Section, { title: "\u0427\u0442\u043E \u0432\u044B \u0441\u043B\u044B\u0448\u0430\u043B\u0438", children: heard.map((h) => (_jsx("li", { className: "border-l-2 border-line pl-2 font-narration text-muted", children: h }, h))) }))] }));
}
/** Атака одной кнопкой: оружие героя против этого существа. Проверяет сервер, модель намерение не разбирает. */
function QuickAttack({ id, name, onDone }) {
    const sheet = useGame((s) => s.sheet);
    const canAct = useGame((s) => s.actions.includes("chat.play"));
    const attacks = sheet?.derived?.attacks ?? [];
    if (!canAct || !attacks.length)
        return null;
    return (_jsxs("div", { className: "flex flex-col gap-1", children: [_jsx("p", { className: "text-xs uppercase tracking-wide text-muted", children: "\u0410\u0442\u0430\u043A\u043E\u0432\u0430\u0442\u044C \u0441\u0440\u0430\u0437\u0443" }), _jsx("div", { className: "flex flex-wrap gap-2", children: attacks.map((a) => (_jsxs("button", { className: "btn border-creature px-2 py-1 text-xs", onClick: () => {
                        const err = attack(id, name, a);
                        if (err)
                            toast.error(err);
                        else
                            onDone();
                    }, children: [a.name, " ", signed(a.attack_bonus)] }, a.key))) })] }));
}
