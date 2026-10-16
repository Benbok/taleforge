// Разметка сущностей: цвет по типу (тема пакета задаёт цвета, типы одинаковы для всех миров) и иконка для
// тех, кто плохо различает цвета.
import type { EntityType } from "../lib/types";
import type { QuickAction } from "./quick";

export const TYPE_COLOR: Record<EntityType, string> = {
  creature: "var(--tf-entity-creature)",
  npc: "var(--tf-entity-npc)",
  item: "var(--tf-entity-item)",
  location: "var(--tf-entity-location)",
  landmark: "var(--tf-entity-location)",
  lore: "var(--tf-entity-lore)",
  hero: "var(--tf-accent)",
  effect: "var(--tf-ember)",
};

export const TYPE_ICON: Record<EntityType, string> = {
  creature: "⚔",
  npc: "☺",
  item: "◆",
  location: "⌖",
  landmark: "▲",
  lore: "❖",
  hero: "★",
  effect: "◈",
};

export const TYPE_NAME: Record<EntityType, string> = {
  creature: "Существо",
  npc: "Персонаж",
  item: "Предмет",
  location: "Место",
  landmark: "Примета",
  lore: "Знание",
  hero: "Герой",
  effect: "Состояние / эффект",
};

/** Что игрок может сделать с сущностью из карточки: текст подставляется в поле ввода, отправляет игрок сам. */
export function cardActions(type: EntityType | undefined, name: string, targetId?: string): { label: string; text: string; action?: QuickAction }[] {
  const action = (label: string, text: string, verb: string) => ({
    label, text, ...(targetId ? { action: { verb, target_id: targetId } } : {}),
  });
  switch (type) {
    case "creature":
      return [
        action("Атаковать", `Атакую: ${name}`, "attack"),
        action("Осмотреть", `Присматриваюсь к: ${name}`, "inspect"),
      ];
    case "npc":
      return [
        { label: "Заговорить", text: `Обращаюсь к: ${name} — ` },
        action("Осмотреть", `Присматриваюсь к: ${name}`, "inspect"),
      ];
    case "item":
      return [
        action("Подобрать", `Подбираю: ${name}`, "pick_up"),
        action("Осмотреть", `Осматриваю: ${name}`, "inspect"),
      ];
    case "location":
      return [
        action("Идти туда", `Иду: ${name}`, "move"),
        action("Осмотреть", `Осматриваю: ${name}`, "inspect"),
      ];
    case "landmark":
      return [action("Осмотреть", `Осматриваю: ${name}`, "inspect")];
    default:
      return [];
  }
}
