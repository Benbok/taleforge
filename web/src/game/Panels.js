import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import Avatar from "../components/Avatar";
import { useGame } from "../stores/game";
import { TYPE_COLOR, TYPE_ICON } from "./entities";
import { useInspector } from "./inspector";
function sceneType(e) {
    if (e.kind === "item")
        return "item";
    return e.attitude === "hostile" ? "creature" : "npc"; // так же делит сервер (core/inspect.entity_type)
}
function Hp({ h }) {
    if (h.hp == null || !h.hp_max)
        return null;
    const pct = Math.max(0, Math.min(100, (h.hp / h.hp_max) * 100));
    const color = pct > 50 ? "var(--color-ok)" : pct > 25 ? "var(--color-warn)" : "var(--color-bad)";
    return (_jsxs("span", { className: "mt-1 block", title: `Хиты ${h.hp} из ${h.hp_max}`, children: [_jsx("span", { className: "block h-1.5 w-full overflow-hidden rounded-full bg-raised", children: _jsx("span", { className: "block h-full transition-[width] duration-500", style: { width: `${pct}%`, background: color } }) }), _jsxs("span", { className: "text-xs text-muted", children: [h.hp, " / ", h.hp_max] })] }));
}
/** Отряд: места за столом, присутствие, у героев — хиты (их видят все участники, как за столом). */
export function PartyPanel() {
    const { seats, heroes, turn, snapshot } = useGame();
    const open = useInspector((s) => s.open);
    const heroBySeat = new Map();
    for (const h of Object.values(heroes))
        if (h.seat_id && (!heroBySeat.has(h.seat_id) || !h.dead))
            heroBySeat.set(h.seat_id, h);
    const sorted = seats
        .slice()
        .sort((a, b) => (a.role === "master" ? -1 : b.role === "master" ? 1 : a.position - b.position));
    return (_jsxs("section", { className: "card p-4", "aria-label": "\u041E\u0442\u0440\u044F\u0434", children: [_jsx("h2", { className: "mb-3 text-base font-semibold", children: "\u041E\u0442\u0440\u044F\u0434" }), _jsx("ul", { className: "flex flex-col gap-3", children: sorted.map((s) => {
                    const h = heroBySeat.get(s.id);
                    const acting = !!turn && turn.seat_id === s.id;
                    const mine = s.id === snapshot?.me.seat_id;
                    const title = s.role === "master"
                        ? s.occupant_type === "agent"
                            ? "ИИ-мастер"
                            : `Мастер: ${s.user_name ?? "—"}`
                        : (h?.name ?? (s.occupant_type === "empty" ? "Свободное место" : "Герой не готов"));
                    return (_jsxs("li", { className: `flex items-start gap-3 rounded-md ${acting ? "bg-raised p-1.5 ring-1 ring-accent" : ""}`, children: [_jsx(Avatar, { name: h?.name ?? s.user_name, role: s.role, occupant: s.occupant_type, presence: s.occupant_type === "human" ? (s.presence ?? "offline") : null }), _jsxs("span", { className: "min-w-0 flex-1", children: [h ? (_jsxs("button", { className: "block max-w-full truncate text-left hover:underline", onClick: (e) => open(h.id, h.name, e.currentTarget), children: [title, mine && _jsx("span", { className: "text-muted", children: " (\u0432\u044B)" }), h.dead && _jsx("span", { className: "text-bad", children: " \u00B7 \u043F\u0430\u043B" })] })) : (_jsx("span", { className: "block truncate", children: title })), s.role === "player" && s.user_name && (_jsxs("span", { className: "block text-xs text-muted", children: [s.user_name, h ? ` · ур. ${h.level}` : "", acting ? " · ходит" : ""] })), h && !h.dead && _jsx(Hp, { h: h })] })] }, s.id));
                }) })] }));
}
/** Сцена: где отряд и кто рядом. Только то, что видно всем; подробности — по клику, в карточке знаний. */
export function ScenePanel() {
    const scene = useGame((s) => s.scene);
    const open = useInspector((s) => s.open);
    if (!scene)
        return null;
    return (_jsxs("section", { className: "card p-4", "aria-label": "\u0421\u0446\u0435\u043D\u0430", children: [_jsxs("div", { className: "mb-2 flex items-center justify-between gap-2", children: [_jsx("h2", { className: "text-base font-semibold", children: "\u0421\u0446\u0435\u043D\u0430" }), scene.mode === "combat" && (_jsxs("span", { className: "rounded-full border border-bad px-2 py-0.5 text-xs text-bad", children: ["\u0411\u043E\u0439 \u00B7 \u0440\u0430\u0443\u043D\u0434 ", scene.round || 1] }))] }), scene.location ? (_jsxs("button", { className: "mb-3 block text-left", style: { color: TYPE_COLOR.location }, onClick: (e) => open(scene.location.id, scene.location.name, e.currentTarget), children: [TYPE_ICON.location, " ", scene.location.name] })) : (_jsx("p", { className: "mb-3 text-muted", children: "\u041C\u0435\u0441\u0442\u043E \u0435\u0449\u0451 \u043D\u0435 \u043D\u0430\u0437\u0432\u0430\u043D\u043E." })), scene.entities.length === 0 ? (_jsx("p", { className: "text-xs text-muted", children: "\u0420\u044F\u0434\u043E\u043C \u043D\u0438\u043A\u043E\u0433\u043E." })) : (_jsx("ul", { className: "flex flex-col gap-1.5", children: scene.entities.map((e) => {
                    const t = sceneType(e);
                    const acting = scene.turn?.actor_id === e.id;
                    return (_jsxs("li", { className: "flex items-baseline justify-between gap-2", children: [_jsxs("button", { className: `truncate text-left underline decoration-dotted underline-offset-4 ${acting ? "font-semibold" : ""}`, style: { color: TYPE_COLOR[t] }, onClick: (ev) => open(e.id, e.name, ev.currentTarget), children: [TYPE_ICON[t], " ", e.name] }), _jsx("span", { className: "shrink-0 text-xs text-muted", children: [e.condition, e.zone, acting ? "ходит" : null].filter(Boolean).join(" · ") })] }, e.id));
                }) }))] }));
}
