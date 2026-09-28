import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useSession } from "../stores/session";
import { toast } from "../stores/toasts";
import { Spinner } from "./ActionButton";
/** Вход и регистрация. С приглашением регистрация идёт по ссылке и сразу занимает место в кампании. */
export default function AuthForm({ inviteToken, initial = "login", onDone, }) {
    const [mode, setMode] = useState(initial);
    const [name, setName] = useState("");
    const [password, setPassword] = useState("");
    const { busy, error, run } = useAsync();
    const signIn = useSession((s) => s.signIn);
    async function submit(e) {
        e.preventDefault();
        const url = mode === "login" ? "/api/auth/login" : inviteToken ? `/api/auth/register/${inviteToken}` : "/api/auth/signup";
        const r = await run(() => api(url, { body: { name: name.trim(), password } }));
        if (r) {
            signIn(r.token, r.user);
            toast.ok(mode === "login" ? `С возвращением, ${r.user.name}` : `Добро пожаловать, ${r.user.name}`);
            onDone?.(mode === "signup" && !!inviteToken);
        }
    }
    return (_jsxs("form", { onSubmit: submit, className: "card flex flex-col gap-3 p-4", children: [_jsx("div", { className: "flex gap-2", role: "tablist", children: ["login", "signup"].map((m) => (_jsx("button", { type: "button", role: "tab", "aria-selected": mode === m, className: `btn flex-1 ${mode === m ? "border-accent" : ""}`, onClick: () => setMode(m), children: m === "login" ? "Вход" : "Регистрация" }, m))) }), _jsxs("label", { className: "flex flex-col gap-1", children: [_jsx("span", { className: "text-muted", children: "\u0418\u043C\u044F" }), _jsx("input", { className: "field", value: name, onChange: (e) => setName(e.target.value), autoComplete: "username", required: true })] }), _jsxs("label", { className: "flex flex-col gap-1", children: [_jsx("span", { className: "text-muted", children: "\u041F\u0430\u0440\u043E\u043B\u044C" }), _jsx("input", { className: "field", type: "password", value: password, onChange: (e) => setPassword(e.target.value), autoComplete: mode === "login" ? "current-password" : "new-password", required: true }), mode === "signup" && _jsx("span", { className: "text-xs text-muted", children: "\u041D\u0435 \u043A\u043E\u0440\u043E\u0447\u0435 6 \u0441\u0438\u043C\u0432\u043E\u043B\u043E\u0432." })] }), error && (_jsxs("p", { className: "text-bad", role: "alert", children: [error, mode === "login" && /неверное/.test(error) ? ". Нет аккаунта? Откройте вкладку «Регистрация»." : ""] })), _jsxs("button", { className: "btn btn-primary", disabled: busy, "aria-busy": busy, children: [busy && _jsx(Spinner, {}), mode === "login" ? "Войти" : "Зарегистрироваться"] })] }));
}
