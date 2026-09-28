import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// Портрет до этапа картинок — инициалы в цвете героя (умолчание по открытому вопросу документа дизайна).
const PRESENCE = { online: "в сети", offline: "не в сети" };
export function initials(name) {
    const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length)
        return "?";
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}
export function hue(name) {
    let h = 0;
    for (const ch of name ?? "")
        h = (h * 31 + ch.charCodeAt(0)) % 360;
    return h;
}
export default function Avatar({ name, role, occupant, presence, size = 32, }) {
    const title = [
        role === "master" ? "Мастер" : null,
        occupant === "empty" ? "свободное место" : name,
        occupant === "agent" ? "играет ИИ" : null,
        presence ? PRESENCE[presence] : null,
    ]
        .filter(Boolean)
        .join(" · ");
    const empty = occupant === "empty";
    return (_jsxs("span", { className: "relative inline-flex", title: title, "aria-label": title, children: [_jsx("span", { className: `inline-flex items-center justify-center rounded-full text-xs font-semibold ${empty ? "border border-dashed border-line text-muted" : "text-white"} ${role === "master" ? "ring-2 ring-accent" : ""}`, style: {
                    width: size,
                    height: size,
                    background: empty ? "transparent" : `hsl(${hue(name)} 35% 38%)`,
                }, children: empty ? "+" : occupant === "agent" && role === "master" ? "ИИ" : initials(name) }), presence && (_jsx("span", { className: `absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${presence === "online" ? "bg-ok" : "bg-line"}` }))] }));
}
