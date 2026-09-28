import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import AuthForm from "../components/AuthForm";
import Header from "../components/Header";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { useSession } from "../stores/session";
import { toast } from "../stores/toasts";
import { Spinner } from "../components/ActionButton";
/** Вход по ссылке: обложка кампании и публичная вводная, имя и пароль — и сразу в лобби. */
export default function InvitePage() {
    const { token = "" } = useParams();
    const user = useSession((s) => s.user);
    const navigate = useNavigate();
    const { busy, error, run } = useAsync();
    const preview = useQuery({
        queryKey: ["invite", token],
        queryFn: () => api(`/api/invites/${token}`),
    });
    async function accept() {
        const c = await run(() => api(`/api/invites/${token}/accept`, { method: "POST" }));
        if (c)
            toast.ok("Вы за столом. Соберите героя, чтобы вступить в игру.");
        if (c)
            navigate(`/c/${c.id}`, { replace: true });
    }
    const p = preview.data;
    return (_jsxs(_Fragment, { children: [_jsx(Header, {}), _jsxs("main", { className: "mx-auto flex max-w-lg flex-col gap-5 px-4 py-8", children: [preview.isLoading && _jsx("p", { className: "text-muted", children: "\u041E\u0442\u043A\u0440\u044B\u0432\u0430\u0435\u043C \u043F\u0440\u0438\u0433\u043B\u0430\u0448\u0435\u043D\u0438\u0435\u2026" }), preview.isError && _jsx("p", { className: "text-bad", children: "\u041F\u0440\u0438\u0433\u043B\u0430\u0448\u0435\u043D\u0438\u0435 \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E." }), p && (_jsxs("section", { className: "card flex flex-col gap-3 p-5", children: [_jsx("p", { className: "text-xs uppercase tracking-wide text-muted", children: "\u041F\u0440\u0438\u0433\u043B\u0430\u0448\u0435\u043D\u0438\u0435 \u0432 \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u044E" }), _jsx("h1", { className: "text-2xl font-semibold", children: p.campaign_name || "Кампания" }), p.public_intro && _jsx("p", { className: "font-narration text-lg leading-relaxed", children: p.public_intro }), p.valid ? (_jsxs("p", { className: "text-muted", children: ["\u0421\u0432\u043E\u0431\u043E\u0434\u043D\u044B\u0445 \u043C\u0435\u0441\u0442: ", p.free_seats] })) : (_jsxs("p", { className: "text-bad", children: ["\u0412\u043E\u0439\u0442\u0438 \u043D\u0435\u043B\u044C\u0437\u044F: ", p.problem] }))] })), p?.valid &&
                        (user ? (_jsxs("div", { className: "flex flex-col gap-2", children: [_jsxs("button", { className: "btn btn-primary", disabled: busy, "aria-busy": busy, onClick: accept, children: [busy && _jsx(Spinner, {}), "\u0421\u0435\u0441\u0442\u044C \u0437\u0430 \u0441\u0442\u043E\u043B \u043A\u0430\u043A ", user.name] }), error && _jsxs("p", { className: "text-bad", role: "alert", children: ["\u041D\u0435 \u043F\u043E\u043B\u0443\u0447\u0438\u043B\u043E\u0441\u044C: ", error] })] })) : (_jsx(AuthForm, { inviteToken: token, initial: "signup", onDone: (joined) => (joined ? navigate("/", { replace: true }) : void accept()) })))] })] }));
}
