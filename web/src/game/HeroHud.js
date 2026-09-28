import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { useGame } from "../stores/game";
import { useExplain } from "./hero";
import { useHeroWindow } from "./HeroWindow";
/** Полоса героя над полем ввода: хиты, КД, эффекты и спасброски от смерти. Каждое число — кнопка с разбором.
 *  Потеря хитов вспыхивает красным с величиной урона, лечение — зелёным. */
export default function HeroHud() {
    const sheet = useGame((s) => s.sheet);
    const explain = useExplain((s) => s.open);
    const showWindow = useHeroWindow((s) => s.show);
    const [flash, setFlash] = useState(null);
    const prev = useRef(null);
    const hp = sheet?.resources.hp ?? null;
    useEffect(() => {
        if (hp == null)
            return;
        if (prev.current != null && hp !== prev.current) {
            setFlash({ delta: hp - prev.current, key: Date.now() });
            const t = setTimeout(() => setFlash(null), 1600);
            prev.current = hp;
            return () => clearTimeout(t);
        }
        prev.current = hp;
    }, [hp]);
    if (!sheet)
        return null;
    const max = sheet.resources.hp_max ?? sheet.derived?.hp_max ?? 0;
    const temp = sheet.resources.temp_hp ?? 0;
    const pct = max ? Math.max(0, Math.min(100, ((hp ?? 0) / max) * 100)) : 0;
    const color = pct > 50 ? "var(--color-ok)" : pct > 25 ? "var(--color-warn)" : "var(--color-bad)";
    const dying = hp === 0 && !sheet.resources.dead;
    const [succ, fail] = sheet.resources.death_saves ?? [0, 0];
    const effects = sheet.derived?.effects ?? [];
    return (_jsxs("div", { className: "flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface px-4 py-2", "aria-label": "\u0412\u0430\u0448 \u0433\u0435\u0440\u043E\u0439", children: [_jsx("button", { className: "font-semibold hover:text-accent", onClick: () => showWindow(), title: "\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u043B\u0438\u0441\u0442 \u0433\u0435\u0440\u043E\u044F", children: sheet.name }), _jsxs("button", { className: `relative flex min-w-[9rem] flex-1 items-center gap-2 rounded-md px-1 sm:max-w-xs ${flash && flash.delta < 0 ? "ring-2 ring-bad" : flash ? "ring-2 ring-ok" : ""}`, onClick: (e) => explain("hp", e.currentTarget), title: "\u0425\u0438\u0442\u044B: \u043F\u043E\u0447\u0435\u043C\u0443 \u0441\u0442\u043E\u043B\u044C\u043A\u043E", children: [_jsx("span", { className: "text-xs text-muted", children: "\u0425\u0438\u0442\u044B" }), _jsx("span", { className: "h-2 flex-1 overflow-hidden rounded-full bg-raised", children: _jsx("span", { className: "block h-full transition-[width] duration-500", style: { width: `${pct}%`, background: color } }) }), _jsxs("span", { className: "tabular-nums", children: [hp ?? "—", "/", max, temp > 0 && _jsxs("span", { className: "text-npc", children: [" +", temp] })] }), flash && (_jsx("span", { className: `tf-pop absolute -top-5 right-0 text-sm font-bold ${flash.delta < 0 ? "text-bad" : "text-ok"}`, "aria-live": "assertive", children: flash.delta > 0 ? `+${flash.delta}` : flash.delta }, flash.key))] }), _jsxs("button", { className: "flex items-baseline gap-1", onClick: (e) => explain("ac", e.currentTarget), title: "\u041A\u043B\u0430\u0441\u0441 \u0434\u043E\u0441\u043F\u0435\u0445\u0430: \u043F\u043E\u0447\u0435\u043C\u0443 \u0441\u0442\u043E\u043B\u044C\u043A\u043E", children: [_jsx("span", { className: "text-xs text-muted", children: "\u041A\u0414" }), _jsx("span", { className: "font-semibold tabular-nums", children: sheet.derived?.ac ?? "—" })] }), dying && (_jsxs("span", { className: "flex items-center gap-1 text-xs", title: "\u0421\u043F\u0430\u0441\u0431\u0440\u043E\u0441\u043A\u0438 \u043E\u0442 \u0441\u043C\u0435\u0440\u0442\u0438: \u0442\u0440\u0438 \u0443\u0441\u043F\u0435\u0445\u0430 \u2014 \u0441\u0442\u0430\u0431\u0438\u043B\u0438\u0437\u0430\u0446\u0438\u044F, \u0442\u0440\u0438 \u043F\u0440\u043E\u0432\u0430\u043B\u0430 \u2014 \u0441\u043C\u0435\u0440\u0442\u044C", children: [_jsx("span", { className: "text-bad", children: "\u041F\u0440\u0438 \u0441\u043C\u0435\u0440\u0442\u0438:" }), [0, 1, 2].map((i) => (_jsx("span", { className: `h-2.5 w-2.5 rounded-full border border-ok ${i < succ ? "bg-ok" : ""}` }, `s${i}`))), _jsx("span", { className: "mx-0.5 text-muted", children: "/" }), [0, 1, 2].map((i) => (_jsx("span", { className: `h-2.5 w-2.5 rounded-full border border-bad ${i < fail ? "bg-bad" : ""}` }, `f${i}`)))] })), sheet.resources.dead && _jsx("span", { className: "text-bad", children: "\u0413\u0435\u0440\u043E\u0439 \u043F\u0430\u043B" }), effects.length > 0 && (_jsx("span", { className: "flex flex-wrap gap-1", children: effects.map((e) => (_jsxs("button", { className: "rounded-full border border-line px-2 py-0.5 text-xs hover:border-accent", onClick: () => showWindow("state"), children: [e.name, e.stacks > 1 ? ` ×${e.stacks}` : ""] }, e.id))) })), _jsx("button", { className: "btn ml-auto px-2 py-1 text-xs", onClick: () => showWindow(), children: "\u041B\u0438\u0441\u0442 \u0433\u0435\u0440\u043E\u044F" })] }));
}
