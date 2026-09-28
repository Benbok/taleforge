// Лист героя: подписи и выбор своего героя. Числа считает сервер, клиент только показывает и спрашивает разбор.
import { create } from "zustand";
import { useGame } from "../stores/game";
export const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"];
export const ABILITY_RU = {
    str: "Сила",
    dex: "Ловкость",
    con: "Телосложение",
    int: "Интеллект",
    wis: "Мудрость",
    cha: "Харизма",
};
export const ABILITY_ABBR = { str: "СИЛ", dex: "ЛОВ", con: "ТЕЛ", int: "ИНТ", wis: "МДР", cha: "ХАР" };
export const SKILLS = [
    ["acrobatics", "Акробатика", "dex"],
    ["animal_handling", "Уход за животными", "wis"],
    ["arcana", "Магия", "int"],
    ["athletics", "Атлетика", "str"],
    ["deception", "Обман", "cha"],
    ["history", "История", "int"],
    ["insight", "Проницательность", "wis"],
    ["intimidation", "Запугивание", "cha"],
    ["investigation", "Анализ", "int"],
    ["medicine", "Медицина", "wis"],
    ["nature", "Природа", "int"],
    ["perception", "Внимательность", "wis"],
    ["performance", "Выступление", "cha"],
    ["persuasion", "Убеждение", "cha"],
    ["religion", "Религия", "int"],
    ["sleight_of_hand", "Ловкость рук", "dex"],
    ["stealth", "Скрытность", "dex"],
    ["survival", "Выживание", "wis"],
];
export const DAMAGE_RU = {
    bludgeoning: "дробящий",
    piercing: "колющий",
    slashing: "рубящий",
    fire: "огнём",
    cold: "холодом",
    acid: "кислотой",
    lightning: "электричеством",
    poison: "ядом",
    necrotic: "некротический",
    radiant: "излучением",
    force: "силовой",
    psychic: "психический",
    thunder: "звуком",
};
export const signed = (n) => (n == null ? "—" : n >= 0 ? `+${n}` : `${n}`);
/** Свой герой: живой на месте зрителя (павший — если другого нет). */
export function myHero(heroes, seatId) {
    if (!seatId)
        return null;
    const mine = Object.values(heroes).filter((h) => h.seat_id === seatId);
    return mine.find((h) => !h.dead) ?? mine[0] ?? null;
}
/** «Почему такое число»: по клику на величину спрашиваем сервер, ответ кешируется до смены листа. */
export const useExplain = create((set) => ({
    stat: null,
    anchor: null,
    open(stat, el) {
        const g = useGame.getState();
        if (g.sheet && !g.explained[stat])
            g.socket?.send("stat.explain", { character_id: g.sheet.id, stat });
        set({ stat, anchor: el?.getBoundingClientRect() ?? null });
    },
    close() {
        set({ stat: null, anchor: null });
    },
}));
