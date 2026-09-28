import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
import { Spinner } from "../components/ActionButton";
import { useGame } from "../stores/game";
import { useExplain } from "./hero";
/** Разбор числа: из чего оно сложилось и, для хитов, последние события, которые их меняли. */
export default function ExplainPopover() {
    const { stat, anchor, close } = useExplain();
    const x = useGame((s) => (stat ? s.explained[stat] : undefined));
    const ref = useRef(null);
    useEffect(() => {
        if (!stat)
            return;
        const onKey = (e) => e.key === "Escape" && close();
        const onDown = (e) => ref.current && !ref.current.contains(e.target) && close();
        window.addEventListener("keydown", onKey);
        window.addEventListener("mousedown", onDown);
        return () => {
            window.removeEventListener("keydown", onKey);
            window.removeEventListener("mousedown", onDown);
        };
    }, [stat, close]);
    if (!stat)
        return null;
    const phone = window.innerWidth < 768;
    const style = anchor && !phone
        ? {
            left: Math.min(Math.max(8, anchor.left), window.innerWidth - 304),
            top: anchor.bottom + 8 + 260 > window.innerHeight ? Math.max(8, anchor.top - 268) : anchor.bottom + 8,
        }
        : undefined;
    return (_jsxs("div", { ref: ref, role: "dialog", "aria-label": "\u041F\u043E\u0447\u0435\u043C\u0443 \u0442\u0430\u043A\u043E\u0435 \u0447\u0438\u0441\u043B\u043E", className: `tf-pop fixed z-50 max-h-[60dvh] overflow-y-auto border border-line bg-raised p-4 shadow-xl ${style ? "w-72 rounded-lg" : "inset-x-0 bottom-0 rounded-t-xl"}`, style: style, children: [_jsxs("div", { className: "mb-2 flex items-start justify-between gap-2", children: [_jsx("p", { className: "text-xs uppercase tracking-wide text-muted", children: "\u041F\u043E\u0447\u0435\u043C\u0443 \u0442\u0430\u043A\u043E\u0435 \u0447\u0438\u0441\u043B\u043E" }), _jsx("button", { className: "text-muted hover:text-ink", onClick: close, "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C", children: "\u00D7" })] }), !x && (_jsxs("p", { className: "flex items-center gap-2 text-muted", children: [_jsx(Spinner, {}), " \u0421\u0447\u0438\u0442\u0430\u0435\u043C\u2026"] })), x?.error && _jsx("p", { className: "text-bad", children: x.error }), x && !x.error && (_jsxs("div", { className: "flex flex-col gap-2", children: [_jsxs("p", { className: "flex items-baseline justify-between gap-2", children: [_jsx("span", { className: "font-semibold", children: x.label }), _jsx("span", { className: "text-2xl font-semibold text-accent", children: x.value ?? "—" })] }), _jsx("ul", { className: "flex flex-col gap-1 border-t border-line pt-2", children: x.parts?.map((p) => (_jsxs("li", { className: "flex justify-between gap-3", children: [_jsx("span", { className: "text-muted", children: p.label }), _jsx("span", { className: "tabular-nums", children: p.value })] }, p.label))) }), x.note && _jsx("p", { className: "text-xs text-muted", children: x.note }), x.history && (_jsxs("div", { className: "border-t border-line pt-2", children: [_jsx("p", { className: "mb-1 text-xs uppercase tracking-wide text-muted", children: "\u041F\u043E\u0441\u043B\u0435\u0434\u043D\u0438\u0435 \u0438\u0437\u043C\u0435\u043D\u0435\u043D\u0438\u044F" }), x.history.length === 0 ? (_jsx("p", { className: "text-xs text-muted", children: "\u041F\u043E\u043A\u0430 \u043D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u0441\u043B\u0443\u0447\u0438\u043B\u043E\u0441\u044C." })) : (_jsx("ul", { className: "flex flex-col gap-1 text-xs", children: x.history.map((h, i) => (_jsx("li", { children: h }, i))) }))] }))] }))] }));
}
