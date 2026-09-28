import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ConnectionBanner from "../components/ConnectionBanner";
import Header from "../components/Header";
import ChatFeed from "../game/ChatFeed";
import Composer from "../game/Composer";
import { useDraft } from "../game/draft";
import EntityPopover from "../game/EntityPopover";
import ExplainPopover from "../game/ExplainPopover";
import { myHero } from "../game/hero";
import HeroHud from "../game/HeroHud";
import HeroWindow from "../game/HeroWindow";
import { PartyPanel, ScenePanel } from "../game/Panels";
import SessionControls from "../game/SessionControls";
import { api } from "../lib/api";
import { actionOf, STATUS_TEXT, statusOf } from "../lib/cards";
import { useGameSocket } from "../lib/useGameSocket";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";
const TABS = [
    ["chat", "Чат"],
    ["party", "Отряд"],
    ["scene", "Сцена"],
];
function About({ card }) {
    const intro = useGame((s) => s.snapshot?.campaign.public_intro);
    if (!intro && !card?.recap)
        return null;
    return (_jsxs("section", { className: "card flex flex-col gap-2 p-4", "aria-label": "\u041E \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438", children: [_jsx("h2", { className: "text-base font-semibold", children: "\u041E \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438" }), intro && _jsx("p", { className: "font-narration leading-relaxed", children: intro }), card?.recap && (_jsxs("p", { className: "font-narration leading-relaxed", children: [_jsx("span", { className: "text-muted", children: "\u0420\u0430\u043D\u0435\u0435 \u0432 \u043A\u0430\u043C\u043F\u0430\u043D\u0438\u0438\u2026 " }), card.recap] }))] }));
}
/** Игровой экран. Компьютер: отряд слева, чат по центру, сцена справа. Планшет: чат и одна колонка сбоку.
 *  Телефон: чат во весь экран, отряд и сцена — вкладками снизу. */
export default function GamePage() {
    const { id = "" } = useParams();
    useGameSocket(id);
    const snapshot = useGame((s) => s.snapshot);
    const setTheme = useSession((s) => s.setTheme);
    const [tab, setTab] = useState("chat");
    const heroes = useGame((s) => s.heroes);
    const heroId = myHero(heroes, snapshot?.me.seat_id)?.id ?? null;
    // полный лист своего героя: при входе — REST, дальше сервер присылает character.sheet после каждого изменения
    useEffect(() => {
        if (!heroId) {
            useGame.getState().setSheet(null);
            return;
        }
        api(`/api/campaigns/${id}/characters/${heroId}`).then((h) => useGame.getState().setSheet(h), () => useGame.getState().setSheet(null));
    }, [id, heroId]);
    useEffect(() => useDraft.getState().load(id), [id]);
    const campaignTheme = useQuery({ queryKey: ["theme", id], queryFn: () => api(`/api/campaigns/${id}/theme`) });
    useEffect(() => {
        if (campaignTheme.data)
            setTheme(campaignTheme.data);
    }, [campaignTheme.data, setTheme]);
    useEffect(() => () => {
        // при уходе из кампании — снова базовая тема
        api("/api/theme").then(useSession.getState().setTheme, () => undefined);
    }, []);
    const cards = useQuery({ queryKey: ["my-campaigns"], queryFn: () => api("/api/me/campaigns") });
    const card = cards.data?.find((c) => c.id === id);
    const heroCta = card && actionOf(card).href.startsWith("/legacy") ? actionOf(card) : null;
    const status = card ? STATUS_TEXT[statusOf(card)] : null;
    const live = !!snapshot?.session;
    const side = (_jsxs(_Fragment, { children: [_jsx(ScenePanel, {}), _jsx(About, { card: card })] }));
    return (_jsxs("div", { className: "flex h-dvh flex-col", children: [_jsxs(Header, { children: [_jsx("span", { className: "min-w-0 truncate font-heading text-base", children: snapshot?.campaign.name ?? card?.name ?? "" }), _jsx("span", { className: `hidden shrink-0 rounded-full border px-2 py-0.5 text-xs sm:inline ${live ? "border-ok text-ok" : "border-line text-muted"}`, children: live ? "Идёт сессия" : snapshot?.campaign.status === "ended" ? "Завершена" : snapshot?.campaign.status === "paused" ? "Пауза" : status }), _jsx("div", { className: "ml-auto hidden md:block", children: _jsx(SessionControls, { campaignId: id }) })] }), _jsx(ConnectionBanner, {}), heroCta && (_jsxs("div", { className: "flex flex-wrap items-center justify-center gap-3 border-b border-line bg-raised px-4 py-2", children: [_jsx("span", { children: heroCta.label === "Новый герой" ? "Ваш герой пал." : "У вас ещё нет готового героя." }), _jsx("a", { className: "btn btn-primary px-3 py-1", href: heroCta.href, children: heroCta.label })] })), _jsxs("div", { className: "mx-auto grid min-h-0 w-full max-w-[96rem] flex-1 md:grid-cols-[1fr_18rem] md:gap-4 md:px-4 md:py-4 lg:grid-cols-[16rem_1fr_18rem]", children: [_jsx("aside", { className: "hidden min-h-0 flex-col gap-4 overflow-y-auto lg:flex", children: _jsx(PartyPanel, {}) }), _jsxs("main", { className: `min-h-0 flex-col overflow-hidden md:flex md:rounded-lg md:border md:border-line md:bg-surface ${tab === "chat" ? "flex" : "hidden"}`, children: [_jsx(ChatFeed, { campaignId: id }), _jsx(HeroHud, {}), _jsx(Composer, {})] }), _jsxs("aside", { className: `min-h-0 flex-col gap-4 overflow-y-auto p-4 md:flex md:p-0 ${tab === "chat" ? "hidden" : "flex"}`, children: [_jsxs("div", { className: `flex flex-col gap-4 lg:hidden ${tab === "scene" ? "hidden md:flex" : ""}`, children: [_jsx("div", { className: "md:hidden", children: _jsx(SessionControls, { campaignId: id }) }), _jsx(PartyPanel, {})] }), _jsx("div", { className: `flex flex-col gap-4 ${tab === "party" ? "hidden md:flex" : ""}`, children: side })] })] }), _jsx("nav", { className: "grid grid-cols-3 border-t border-line bg-surface md:hidden", "aria-label": "\u0420\u0430\u0437\u0434\u0435\u043B\u044B", children: TABS.map(([t, name]) => (_jsx("button", { className: `py-3 text-sm ${tab === t ? "font-semibold text-accent" : "text-muted"}`, "aria-current": tab === t ? "page" : undefined, onClick: () => setTab(t), children: name }, t))) }), _jsx(EntityPopover, {}), _jsx(ExplainPopover, {}), _jsx(HeroWindow, {})] }));
}
