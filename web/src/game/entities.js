export const TYPE_COLOR = {
    creature: "var(--tf-entity-creature)",
    npc: "var(--tf-entity-npc)",
    item: "var(--tf-entity-item)",
    location: "var(--tf-entity-location)",
    lore: "var(--tf-entity-lore)",
    hero: "var(--tf-accent)",
};
export const TYPE_ICON = {
    creature: "⚔",
    npc: "☺",
    item: "◆",
    location: "⌖",
    lore: "❖",
    hero: "★",
};
export const TYPE_NAME = {
    creature: "Существо",
    npc: "Персонаж",
    item: "Предмет",
    location: "Место",
    lore: "Знание",
    hero: "Герой",
};
/** Что игрок может сделать с сущностью из карточки: текст подставляется в поле ввода, отправляет игрок сам. */
export function cardActions(type, name) {
    switch (type) {
        case "creature":
            return [
                { label: "Атаковать", text: `Атакую: ${name}` },
                { label: "Осмотреть", text: `Присматриваюсь к: ${name}` },
            ];
        case "npc":
            return [
                { label: "Заговорить", text: `Обращаюсь к: ${name} — ` },
                { label: "Осмотреть", text: `Присматриваюсь к: ${name}` },
            ];
        case "item":
            return [
                { label: "Подобрать", text: `Подбираю: ${name}` },
                { label: "Осмотреть", text: `Осматриваю: ${name}` },
            ];
        case "location":
            return [
                { label: "Идти туда", text: `Иду: ${name}` },
                { label: "Осмотреть", text: `Осматриваю: ${name}` },
            ];
        default:
            return [];
    }
}
