import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
const OUTCOME = {
    success: { text: "Успех", cls: "text-ok" },
    fail: { text: "Провал", cls: "text-bad" },
    hit: { text: "Попадание", cls: "text-ok" },
    crit: { text: "Критическое попадание", cls: "text-ok" },
    miss: { text: "Промах", cls: "text-bad" },
};
const MODE = { advantage: "с преимуществом", disadvantage: "с помехой" };
/** Карточка броска: что проверялось, кубик, итог против сложности, успех или провал цветом; по нажатию — разбор. */
export default function RollCardView({ card }) {
    const [open, setOpen] = useState(false);
    const out = OUTCOME[card.outcome];
    const roll = card.roll;
    return (_jsxs("div", { className: "tf-pop mx-auto w-full max-w-md", children: [_jsxs("button", { type: "button", onClick: () => setOpen(!open), "aria-expanded": open, className: "flex w-full items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-left hover:border-accent", children: [roll?.total != null ? (_jsx("span", { className: `flex h-10 w-10 shrink-0 items-center justify-center rounded-md border-2 text-lg font-semibold ${card.outcome === "fail" || card.outcome === "miss" ? "border-bad" : card.outcome === "info" ? "border-line" : "border-ok"}`, "aria-label": `итог ${roll.total}`, children: roll.total })) : (_jsx("span", { className: "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border-2 border-line text-lg", "aria-hidden": true, children: "\u2684" })), _jsxs("span", { className: "min-w-0 flex-1", children: [_jsx("span", { className: "block truncate font-semibold", children: card.title }), _jsxs("span", { className: "block truncate text-xs text-muted", children: [[card.who, card.target && `→ ${card.target}`, card.against && `против ${card.against.label} ${card.against.value}`]
                                        .filter(Boolean)
                                        .join(" "), card.order && card.order.map((x) => `${x.name ?? "?"} ${x.initiative}`).join(" · ")] })] }), _jsxs("span", { className: "shrink-0 text-right", children: [out && _jsx("span", { className: `block font-semibold ${out.cls}`, children: out.text }), card.damage && _jsxs("span", { className: "block text-xs", children: ["\u0443\u0440\u043E\u043D ", card.damage.amount] })] })] }), open && (_jsxs("div", { className: "mt-1 rounded-lg border border-line bg-raised px-3 py-2 text-xs leading-relaxed", children: [roll?.natural != null && (_jsxs("p", { children: ["d20: ", roll.d20 && roll.d20.length > 1 ? `${roll.d20.join(" и ")} → ` : "", roll.natural, roll.modifier ? ` ${roll.modifier > 0 ? "+" : "−"} ${Math.abs(roll.modifier)}` : "", " = ", roll.total, roll.mode && MODE[roll.mode] ? ` (${MODE[roll.mode]})` : ""] })), card.damage && (_jsxs("p", { children: ["\u0423\u0440\u043E\u043D: ", card.damage.dice.map((d) => `${d.expr} = ${d.total}`).join(", "), " \u2014 \u0432\u0441\u0435\u0433\u043E ", card.damage.amount, card.damage.type ? `, ${card.damage.type}` : ""] })), card.dice && card.dice.length > 0 && _jsxs("p", { children: ["\u041A\u0443\u0431\u0438\u043A\u0438: ", card.dice.map((d) => `${d.expr} = ${d.total}`).join(", ")] }), card.track && (_jsxs("p", { children: ["\u0423\u0441\u043F\u0435\u0445\u0438 ", card.track.successes, " \u0438\u0437 3 \u00B7 \u043F\u0440\u043E\u0432\u0430\u043B\u044B ", card.track.failures, " \u0438\u0437 3"] })), card.reason && _jsxs("p", { className: "text-muted", children: ["\u0417\u0430\u0447\u0435\u043C: ", card.reason] }), card.notes?.map((n) => (_jsx("p", { children: n }, n)))] }))] }));
}
