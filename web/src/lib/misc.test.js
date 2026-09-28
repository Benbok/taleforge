import { describe, expect, it } from "vitest";
import { initials } from "../components/Avatar";
import { actionOf, groupCards, statusOf } from "./cards";
import { parseMarkup, plain } from "./markup";
import { cssVars } from "./theme";
const card = (over) => ({
    id: "c1",
    name: "К",
    world: null,
    status: "active",
    session_live: false,
    waiting_players: 0,
    my_role: "player",
    is_owner: false,
    hero: { id: "h", name: "Бран", status: "approved", level: 1 },
    party: [],
    recap: null,
    last_session_at: null,
    created_at: "2026-09-28T00:00:00Z",
    ...over,
});
describe("карточки кампаний", () => {
    it("раскладывает по группам в порядке документа", () => {
        const groups = groupCards([
            card({ id: "a", status: "ended" }),
            card({ id: "b", my_role: "master" }),
            card({ id: "c", session_live: true }),
            card({ id: "d" }),
            card({ id: "e", my_role: null, is_owner: true }),
        ]);
        expect(groups.map(([g, l]) => [g, l.map((c) => c.id)])).toEqual([
            ["live", ["c"]],
            ["playing", ["d"]],
            ["leading", ["b"]],
            ["created", ["e"]],
            ["archive", ["a"]],
        ]);
    });
    it("выбирает действие и статус по ситуации", () => {
        expect(actionOf(card({ hero: null })).label).toBe("Собрать героя");
        expect(actionOf(card({ hero: null })).href).toBe("/legacy?campaign=c1");
        expect(actionOf(card({ hero: { id: "h", name: "Б", status: "submitted", level: 1 } })).label).toBe("Персонаж на проверке");
        expect(actionOf(card({ session_live: true }))).toEqual({ label: "Продолжить", href: "/c/c1", primary: true });
        expect(actionOf(card({ my_role: null, is_owner: true, hero: null })).label).toBe("Управлять");
        expect(statusOf(card({ status: "lobby", waiting_players: 2 }))).toBe("waiting");
        expect(statusOf(card({ status: "paused" }))).toBe("paused");
    });
});
describe("разметка и тема", () => {
    it("разбирает [[id|текст]]", () => {
        expect(parseMarkup("У [[en_1|причала]] ждёт [[ch_2|Бран]].")).toEqual([
            { text: "У " },
            { id: "en_1", text: "причала" },
            { text: " ждёт " },
            { id: "ch_2", text: "Бран" },
            { text: "." },
        ]);
        expect(plain("без разметки")).toBe("без разметки");
        expect(plain("**Иван**, вы прибыли в [[en_1|Деревню]]")).toBe("Иван, вы прибыли в Деревню"); // жирный от модели
    });
    it("превращает тему в CSS-переменные выбранного режима", () => {
        const t = {
            dark: { bg: "#000000", entity_npc: "#111111" },
            light: { bg: "#ffffff" },
            fonts: { narration: "Lora", ui: "Inter", heading: "Lora" },
            font_css: null,
            labels: {},
        };
        expect(cssVars(t, "dark")).toMatchObject({ "--tf-bg": "#000000", "--tf-entity-npc": "#111111", "--tf-font-ui": "Inter" });
        expect(cssVars(t, "light")["--tf-bg"]).toBe("#ffffff");
    });
    it("делает инициалы портрета", () => {
        expect(initials("лина морская")).toBe("ЛМ");
        expect(initials(null)).toBe("?");
    });
});
