import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../stores/session";
export function ThemeToggle() {
    const { mode, toggleMode } = useSession();
    return (_jsx("button", { className: "btn px-2 py-1", onClick: toggleMode, title: "\u0421\u043C\u0435\u043D\u0438\u0442\u044C \u0442\u0435\u043C\u0443", "aria-label": "\u0421\u043C\u0435\u043D\u0438\u0442\u044C \u0442\u0435\u043C\u0443", children: mode === "dark" ? "☾" : "☀" }));
}
export default function Header({ children }) {
    const { user, signOut } = useSession();
    const navigate = useNavigate();
    return (_jsxs("header", { className: "flex items-center gap-3 border-b border-line bg-surface px-4 py-3", children: [_jsx(Link, { to: "/", className: "font-heading text-lg font-semibold text-ink no-underline", children: "Taleforge" }), _jsx("div", { className: "flex min-w-0 flex-1 items-center gap-2", children: children }), _jsx(ThemeToggle, {}), user && (_jsxs(_Fragment, { children: [_jsx("a", { className: "hidden text-muted hover:text-ink sm:inline", href: "/legacy", title: "\u041F\u0440\u043E\u0444\u0438\u043B\u044C, \u0433\u0435\u0440\u043E\u0438 \u0438 \u043D\u0430\u0441\u0442\u0440\u043E\u0439\u043A\u0438 \u2014 \u043F\u043E\u043A\u0430 \u0432 \u043F\u0440\u0435\u0436\u043D\u0435\u043C \u043A\u043B\u0438\u0435\u043D\u0442\u0435", children: user.name }), _jsx("button", { className: "btn px-2 py-1", onClick: () => {
                            signOut();
                            navigate("/");
                        }, children: "\u0412\u044B\u0439\u0442\u0438" })] }))] }));
}
