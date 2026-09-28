import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { ThemeToggle } from "../components/Header";
import AuthForm from "../components/AuthForm";
export default function Welcome() {
    return (_jsxs("main", { className: "mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-4 py-10", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("h1", { className: "text-3xl font-semibold", children: "Taleforge" }), _jsx(ThemeToggle, {})] }), _jsx("p", { className: "font-narration text-lg text-muted", children: "\u0420\u043E\u043B\u0435\u0432\u0430\u044F \u0438\u0433\u0440\u0430 \u0432 \u0442\u0435\u043A\u0441\u0442\u0435: \u043C\u0430\u0441\u0442\u0435\u0440 \u0432\u0435\u0434\u0451\u0442 \u0438\u0441\u0442\u043E\u0440\u0438\u044E \u043F\u043E \u043F\u0440\u0430\u0432\u0438\u043B\u0430\u043C D&D, \u0430 \u0432\u044B \u0440\u0435\u0448\u0430\u0435\u0442\u0435, \u0447\u0442\u043E \u0434\u0435\u043B\u0430\u044E\u0442 \u0432\u0430\u0448\u0438 \u0433\u0435\u0440\u043E\u0438." }), _jsx(AuthForm, {})] }));
}
