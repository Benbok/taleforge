import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect } from "react";
import { create } from "zustand";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { ABILITIES, ABILITY_ABBR, ABILITY_RU, DAMAGE_RU, signed, SKILLS, useExplain } from "./hero";
import { attack } from "./quick";
const TABS = [
    ["stats", "Характеристики"],
    ["combat", "Бой"],
    ["gear", "Снаряжение"],
    ["state", "Состояние"],
    ["persona", "Личность"],
    ["log", "Журнал"],
];
export const useHeroWindow = create((set) => ({
    open: false,
    tab: "stats",
    show(tab) {
        set((s) => ({ open: true, tab: tab ?? s.tab }));
    },
    hide() {
        set({ open: false });
    },
    setTab(tab) {
        set({ tab });
    },
}));
/** Число с разбором по клику. */
function Num({ stat, children, className = "" }) {
    const explain = useExplain((s) => s.open);
    return (_jsx("button", { className: `rounded tabular-nums underline decoration-dotted underline-offset-4 hover:text-accent ${className}`, onClick: (e) => explain(stat, e.currentTarget), title: "\u041F\u043E\u0447\u0435\u043C\u0443 \u0442\u0430\u043A\u043E\u0435 \u0447\u0438\u0441\u043B\u043E", children: children }));
}
function Stats({ h }) {
    const d = h.derived;
    const skills = new Set(h.sheet.skills ?? []);
    return (_jsxs("div", { className: "flex flex-col gap-4", children: [_jsx("div", { className: "grid grid-cols-3 gap-2 sm:grid-cols-6", children: ABILITIES.map((a) => (_jsxs("div", { className: "card flex flex-col items-center p-2", children: [_jsx("span", { className: "text-xs text-muted", children: ABILITY_ABBR[a] }), _jsx(Num, { stat: `ability:${a}`, className: "text-xl font-semibold", children: d.abilities[a] }), _jsx("span", { className: "text-xs", children: signed(d.mods[a]) })] }, a))) }), _jsxs("div", { className: "flex flex-wrap gap-4", children: [_jsxs("span", { children: ["\u0411\u043E\u043D\u0443\u0441 \u043C\u0430\u0441\u0442\u0435\u0440\u0441\u0442\u0432\u0430 ", _jsx(Num, { stat: "pb", children: signed(d.pb) })] }), _jsxs("span", { children: ["\u0418\u043D\u0438\u0446\u0438\u0430\u0442\u0438\u0432\u0430 ", _jsx(Num, { stat: "initiative", children: signed(d.mods.dex) })] }), _jsxs("span", { children: ["\u041F\u0430\u0441\u0441\u0438\u0432\u043D\u0430\u044F \u0432\u043D\u0438\u043C\u0430\u0442\u0435\u043B\u044C\u043D\u043E\u0441\u0442\u044C ", _jsx(Num, { stat: "passive_perception", children: 10 + d.skills.perception })] }), _jsxs("span", { children: ["\u0421\u043A\u043E\u0440\u043E\u0441\u0442\u044C ", _jsxs(Num, { stat: "speed", children: [d.speed ?? 30, " \u0444\u0442"] })] })] }), _jsxs("div", { children: [_jsx("h3", { className: "mb-1 text-sm text-muted", children: "\u0421\u043F\u0430\u0441\u0431\u0440\u043E\u0441\u043A\u0438" }), _jsx("div", { className: "grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3", children: ABILITIES.map((a) => (_jsxs("span", { className: "flex justify-between", children: [ABILITY_RU[a], " ", _jsx(Num, { stat: `save:${a}`, children: signed(d.saves[a]) })] }, a))) })] }), _jsxs("div", { children: [_jsx("h3", { className: "mb-1 text-sm text-muted", children: "\u041D\u0430\u0432\u044B\u043A\u0438 (\u25CF \u2014 \u0432\u043B\u0430\u0434\u0435\u043D\u0438\u0435)" }), _jsx("div", { className: "grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2", children: SKILLS.map(([key, name, a]) => (_jsxs("span", { className: "flex justify-between", children: [_jsxs("span", { children: [_jsx("span", { className: skills.has(key) ? "text-accent" : "text-line", children: "\u25CF" }), " ", name, " ", _jsx("span", { className: "text-xs text-muted", children: ABILITY_ABBR[a] })] }), _jsx(Num, { stat: `skill:${key}`, children: signed(d.skills[key]) })] }, key))) })] })] }));
}
function Combat({ h }) {
    const scene = useGame((s) => s.scene);
    const canAct = useGame((s) => s.actions.includes("chat.play"));
    const reason = useGame((s) => s.blocked["chat.play"]);
    const hide = useHeroWindow((s) => s.hide);
    const targets = (scene?.entities ?? []).filter((e) => e.attitude === "hostile" && e.condition !== "мёртв");
    const d = h.derived;
    function hit(t, a) {
        const err = attack(t.id, t.name, a);
        if (err)
            toast.error(err);
        else
            hide();
    }
    return (_jsxs("div", { className: "flex flex-col gap-3", children: [_jsxs("p", { className: "flex gap-4", children: [_jsxs("span", { children: ["\u041A\u0414 ", _jsx(Num, { stat: "ac", children: d.ac })] }), _jsxs("span", { children: ["\u0425\u0438\u0442\u044B ", _jsx(Num, { stat: "hp", children: h.resources.hp }), "/", _jsx(Num, { stat: "hp_max", children: h.resources.hp_max })] })] }), !canAct && reason && _jsx("p", { className: "text-xs text-warn", children: reason }), _jsx("ul", { className: "flex flex-col gap-3", children: d.attacks.map((a) => (_jsxs("li", { className: "card flex flex-col gap-2 p-3", children: [_jsxs("p", { className: "flex flex-wrap items-baseline justify-between gap-2", children: [_jsx("span", { className: "font-semibold", children: a.name }), _jsxs("span", { className: "text-sm", children: ["\u043F\u043E\u043F\u0430\u0434\u0430\u043D\u0438\u0435 ", _jsx(Num, { stat: `attack:${a.key}`, children: signed(a.attack_bonus) }), " \u00B7 \u0443\u0440\u043E\u043D ", a.damage, " ", DAMAGE_RU[a.damage_type] ?? a.damage_type, " \u00B7 ", a.kind === "ranged" ? "дальний бой" : "ближний бой"] })] }), canAct && targets.length > 0 && (_jsx("div", { className: "flex flex-wrap gap-2", children: targets.map((t) => (_jsxs("button", { className: "btn px-2 py-1 text-xs", onClick: () => hit(t, a), children: ["\u0410\u0442\u0430\u043A\u043E\u0432\u0430\u0442\u044C: ", t.name] }, t.id))) }))] }, a.key))) }), canAct && targets.length === 0 && _jsx("p", { className: "text-xs text-muted", children: "\u0420\u044F\u0434\u043E\u043C \u043D\u0435\u0442 \u0432\u0440\u0430\u0433\u043E\u0432: \u0430\u0442\u0430\u043A\u043E\u0432\u0430\u0442\u044C \u043D\u0435\u043A\u043E\u0433\u043E." })] }));
}
function Gear({ h }) {
    if (!h.inventory.length)
        return _jsx("p", { className: "text-muted", children: "\u0421\u043D\u0430\u0440\u044F\u0436\u0435\u043D\u0438\u044F \u043D\u0435\u0442." });
    return (_jsx("ul", { className: "flex flex-col gap-1", children: h.inventory.map((i) => (_jsxs("li", { className: "flex justify-between gap-2 border-b border-line py-1", children: [_jsxs("span", { children: [i.name, i.qty > 1 ? ` ×${i.qty}` : ""] }), i.equipped && _jsx("span", { className: "text-xs text-accent", children: "\u043D\u0430\u0434\u0435\u0442\u043E" })] }, i.id))) }));
}
function State({ h }) {
    const r = h.resources;
    const [s, f] = r.death_saves ?? [0, 0];
    const effects = h.derived?.effects ?? [];
    return (_jsxs("div", { className: "flex flex-col gap-3", children: [_jsxs("p", { children: ["\u0425\u0438\u0442\u044B ", _jsx(Num, { stat: "hp", children: r.hp }), " \u0438\u0437 ", _jsx(Num, { stat: "hp_max", children: r.hp_max }), r.temp_hp ? ` · временные ${r.temp_hp}` : ""] }), _jsxs("p", { children: ["\u041A\u043E\u0441\u0442\u0438 \u0445\u0438\u0442\u043E\u0432: ", r.hit_dice ?? 0, " \u2014 \u0442\u0440\u0430\u0442\u044F\u0442\u0441\u044F \u043D\u0430 \u043A\u043E\u0440\u043E\u0442\u043A\u043E\u043C \u043E\u0442\u0434\u044B\u0445\u0435."] }), _jsxs("p", { children: ["\u0421\u043F\u0430\u0441\u0431\u0440\u043E\u0441\u043A\u0438 \u043E\u0442 \u0441\u043C\u0435\u0440\u0442\u0438: \u0443\u0441\u043F\u0435\u0445\u0438 ", s, "/3, \u043F\u0440\u043E\u0432\u0430\u043B\u044B ", f, "/3"] }), _jsxs("div", { children: [_jsx("h3", { className: "mb-1 text-sm text-muted", children: "\u042D\u0444\u0444\u0435\u043A\u0442\u044B" }), effects.length === 0 ? (_jsx("p", { className: "text-muted", children: "\u041D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0443\u0435\u0442." })) : (_jsx("ul", { className: "flex flex-col gap-1", children: effects.map((e) => (_jsxs("li", { children: [e.name, e.stacks > 1 ? ` ×${e.stacks}` : ""] }, e.id))) }))] })] }));
}
function Persona({ h }) {
    return (_jsxs("div", { className: "flex flex-col gap-3 font-narration", children: [h.public_bio && (_jsxs("section", { children: [_jsx("h3", { className: "font-ui text-sm text-muted", children: "\u0427\u0442\u043E \u0432\u0438\u0434\u044F\u0442 \u0432\u0441\u0435" }), _jsx("p", { children: h.public_bio })] })), h.personality && (_jsxs("section", { children: [_jsx("h3", { className: "font-ui text-sm text-muted", children: "\u0425\u0430\u0440\u0430\u043A\u0442\u0435\u0440" }), _jsx("p", { children: h.personality })] })), h.private_backstory && (_jsxs("section", { children: [_jsx("h3", { className: "font-ui text-sm text-muted", children: "\u0422\u0430\u0439\u043D\u0430\u044F \u0438\u0441\u0442\u043E\u0440\u0438\u044F (\u0432\u0438\u0434\u0438\u0442\u0435 \u0442\u043E\u043B\u044C\u043A\u043E \u0432\u044B \u0438 \u043C\u0430\u0441\u0442\u0435\u0440)" }), _jsx("p", { children: h.private_backstory })] })), h.bonds && h.bonds.length > 0 && (_jsxs("section", { children: [_jsx("h3", { className: "font-ui text-sm text-muted", children: "\u0421\u0432\u044F\u0437\u0438, \u0438\u0437\u0432\u0435\u0441\u0442\u043D\u044B\u0435 \u043E\u0442\u0440\u044F\u0434\u0443" }), _jsx("ul", { children: h.bonds.map((b) => (_jsxs("li", { children: [_jsxs("span", { className: "text-muted", children: [b.question, " "] }), b.answer] }, b.question))) })] }))] }));
}
function Log() {
    const g = useGame();
    const x = g.explained.hp;
    useEffect(() => {
        if (g.sheet && !x)
            g.socket?.send("stat.explain", { character_id: g.sheet.id, stat: "hp" });
    }, [g.sheet, g.socket, x]);
    if (!x)
        return _jsx("p", { className: "text-muted", children: "\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u043C \u0436\u0443\u0440\u043D\u0430\u043B\u2026" });
    if (x.error)
        return _jsx("p", { className: "text-bad", children: x.error });
    return x.history?.length ? (_jsx("ul", { className: "flex flex-col gap-1", children: x.history.map((h, i) => (_jsx("li", { className: "border-b border-line py-1", children: h }, i))) })) : (_jsx("p", { className: "text-muted", children: "\u041F\u043E\u043A\u0430 \u0433\u0435\u0440\u043E\u0439 \u043D\u0435 \u043F\u043E\u043B\u0443\u0447\u0430\u043B \u0443\u0440\u043E\u043D\u0430 \u0438 \u043D\u0435 \u043B\u0435\u0447\u0438\u043B\u0441\u044F." }));
}
/** Окно героя: вкладки листа. Числа кликабельны и открывают разбор; из «Боя» можно атаковать одной кнопкой. */
export default function HeroWindow() {
    const { open, tab, hide, setTab } = useHeroWindow();
    const sheet = useGame((s) => s.sheet);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => e.key === "Escape" && !document.querySelector('[aria-label="Почему такое число"]') && hide();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, hide]);
    if (!open || !sheet)
        return null;
    const ready = !!sheet.derived;
    return (_jsx("div", { className: "fixed inset-0 z-40 flex items-end justify-center bg-black/50 md:items-center", onMouseDown: (e) => e.target === e.currentTarget && hide(), children: _jsxs("div", { role: "dialog", "aria-label": "\u041B\u0438\u0441\u0442 \u0433\u0435\u0440\u043E\u044F", className: "tf-pop flex max-h-[90dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-xl border border-line bg-surface md:rounded-xl", children: [_jsxs("header", { className: "flex items-start justify-between gap-3 border-b border-line p-4", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-xl font-semibold", children: sheet.name }), _jsx("p", { className: "text-muted", children: [sheet.origin_name, sheet.class_name, `${sheet.level} уровень`].filter(Boolean).join(" · ") })] }), _jsx("button", { className: "text-2xl leading-none text-muted hover:text-ink", onClick: hide, "aria-label": "\u0417\u0430\u043A\u0440\u044B\u0442\u044C", children: "\u00D7" })] }), _jsx("nav", { className: "flex gap-1 overflow-x-auto border-b border-line px-2", "aria-label": "\u0420\u0430\u0437\u0434\u0435\u043B\u044B \u043B\u0438\u0441\u0442\u0430", children: TABS.map(([t, name]) => (_jsx("button", { className: `shrink-0 border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent text-ink" : "border-transparent text-muted"}`, onClick: () => setTab(t), children: name }, t))) }), _jsx("div", { className: "overflow-y-auto p-4", children: !ready && tab !== "persona" ? (_jsx("p", { className: "text-muted", children: "\u041B\u0438\u0441\u0442 \u0435\u0449\u0451 \u043D\u0435 \u0441\u043E\u0431\u0440\u0430\u043D: \u0437\u0430\u043A\u043E\u043D\u0447\u0438\u0442\u0435 \u0433\u0435\u0440\u043E\u044F \u0432 \u043A\u043E\u043D\u0441\u0442\u0440\u0443\u043A\u0442\u043E\u0440\u0435." })) : tab === "stats" ? (_jsx(Stats, { h: sheet })) : tab === "combat" ? (_jsx(Combat, { h: sheet })) : tab === "gear" ? (_jsx(Gear, { h: sheet })) : tab === "state" ? (_jsx(State, { h: sheet })) : tab === "persona" ? (_jsx(Persona, { h: sheet })) : (_jsx(Log, {})) })] }) }));
}
