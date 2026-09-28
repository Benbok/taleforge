import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { toast } from "../stores/toasts";
/** Кнопка с запросом: пока идёт — крутится и не нажимается повторно; успех — уведомление, ошибка — причина
 *  от сервера прямо под кнопкой. */
export default function ActionButton({ run, done, children, primary, danger, confirm, className = "", title, }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    async function click() {
        if (busy)
            return;
        if (confirm && !window.confirm(confirm))
            return;
        setBusy(true);
        setError(null);
        try {
            await run();
            if (done)
                toast.ok(done);
        }
        catch (e) {
            const text = e instanceof Error ? e.message : String(e);
            setError(text);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs("span", { className: "inline-flex flex-col gap-1", children: [_jsxs("button", { className: `btn ${primary ? "btn-primary" : ""} ${danger ? "border-bad text-bad" : ""} ${className}`, onClick: click, disabled: busy, "aria-busy": busy, title: title, children: [busy && _jsx(Spinner, {}), children] }), error && (_jsx("span", { role: "alert", className: "max-w-xs text-xs text-bad", children: error }))] }));
}
export function Spinner() {
    return (_jsx("span", { "aria-hidden": true, className: "inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" }));
}
