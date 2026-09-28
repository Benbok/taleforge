import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useToasts } from "../stores/toasts";
const TONE = {
    ok: "border-ok",
    error: "border-bad",
    info: "border-accent",
};
const ICON = { ok: "✓", error: "!", info: "i" };
/** Уведомления внизу экрана: результат действия и понятная причина ошибки. */
export default function Toasts() {
    const { items, dismiss } = useToasts();
    return (_jsx("div", { "aria-live": "polite", className: "pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-auto md:top-16 md:items-end", children: items.map((t) => (_jsxs("div", { role: t.tone === "error" ? "alert" : "status", className: `tf-pop pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border-l-4 bg-raised px-4 py-3 shadow-lg ${TONE[t.tone]}`, children: [_jsx("span", { className: `mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${t.tone === "error" ? "bg-bad text-white" : t.tone === "ok" ? "bg-ok text-white" : "bg-accent text-on-accent"}`, "aria-hidden": true, children: ICON[t.tone] }), _jsx("p", { className: "flex-1", children: t.text }), _jsx("button", { className: "text-muted hover:text-ink", onClick: () => dismiss(t.id), "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C", children: "\u00D7" })] }, t.id))) }));
}
