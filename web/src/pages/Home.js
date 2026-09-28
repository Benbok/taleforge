import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import CampaignCardView from "../components/CampaignCardView";
import Header from "../components/Header";
import { api } from "../lib/api";
import { actionOf, GROUP_TITLES, groupCards } from "../lib/cards";
import { useSession } from "../stores/session";
export default function Home() {
    const user = useSession((s) => s.user);
    const isAdmin = user.platform_role !== "player";
    const cards = useQuery({
        queryKey: ["my-campaigns"],
        queryFn: () => api("/api/me/campaigns"),
        refetchInterval: 30000,
    });
    const list = cards.data ?? [];
    const next = list.find((c) => c.session_live && actionOf(c).label === "Продолжить");
    return (_jsxs(_Fragment, { children: [_jsx(Header, { children: isAdmin && (_jsx("a", { className: "btn btn-primary px-3 py-1", href: "/legacy", title: "\u0421\u043E\u0437\u0434\u0430\u043D\u0438\u0435 \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438 \u043F\u043E\u043A\u0430 \u0432 \u043F\u0440\u0435\u0436\u043D\u0435\u043C \u043A\u043B\u0438\u0435\u043D\u0442\u0435", children: "\u041D\u043E\u0432\u0430\u044F \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u044F" })) }), _jsxs("main", { className: "mx-auto flex max-w-6xl flex-col gap-8 px-4 py-6", children: [next && (_jsxs("section", { className: "card flex flex-wrap items-center justify-between gap-3 border-accent p-4", children: [_jsxs("div", { children: [_jsx("p", { className: "text-muted", children: "\u0418\u0434\u0451\u0442 \u0441\u0435\u0441\u0441\u0438\u044F" }), _jsx("p", { className: "text-xl font-semibold", children: next.name })] }), _jsx(Link, { to: `/c/${next.id}`, className: "btn btn-primary", children: "\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0438\u0442\u044C" })] })), cards.isLoading && _jsx("p", { className: "text-muted", children: "\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u043C \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438\u2026" }), cards.isError && _jsxs("p", { className: "text-bad", children: ["\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438: ", cards.error.message] }), cards.isSuccess && list.length === 0 && (_jsxs("section", { className: "card p-6 text-center", children: [_jsx("p", { className: "text-lg", children: "\u041F\u043E\u043A\u0430 \u043D\u0435\u0442 \u043D\u0438 \u043E\u0434\u043D\u043E\u0439 \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438." }), _jsx("p", { className: "text-muted", children: isAdmin ? "Создайте первую кнопкой «Новая кампания»." : "Попросите у владельца кампании ссылку-приглашение." })] })), groupCards(list).map(([group, items]) => (_jsxs("section", { className: "flex flex-col gap-3", children: [_jsx("h2", { className: "text-lg text-muted", children: GROUP_TITLES[group] }), _jsx("div", { className: "grid gap-4 sm:grid-cols-2 lg:grid-cols-3", children: items.map((c) => (_jsx(CampaignCardView, { c: c }, c.id))) })] }, group)))] })] }));
}
