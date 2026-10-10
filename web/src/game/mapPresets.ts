import type { EntityType } from "../lib/types";
import type { SketchExit, SketchFeature } from "./map";
import type { MapGlyphName } from "./MapGlyph";

export type TokenShape = "round" | "hex" | "diamond" | "square";

export interface MapVisualPreset {
  /** Только представление. Не влияет на тип Entity, игровую механику и видимость. */
  family: EntityType | "exit" | "feature";
  glyph: MapGlyphName;
  color: string;
  shape: TokenShape;
  label: string;
}

/** Семантические стили: цвета задаются темой, силуэт и рисунок различимы без цвета. */
export const MAP_PRESETS: Record<EntityType, MapVisualPreset> = {
  hero: { family: "hero", glyph: "hero", color: "var(--tf-accent)", shape: "hex", label: "Герой" },
  creature: { family: "creature", glyph: "enemy", color: "var(--tf-entity-creature)", shape: "round", label: "Противник" },
  npc: { family: "npc", glyph: "person", color: "var(--tf-entity-npc)", shape: "round", label: "Персонаж" },
  item: { family: "item", glyph: "gem", color: "var(--tf-entity-item)", shape: "diamond", label: "Предмет" },
  landmark: { family: "landmark", glyph: "landmark", color: "var(--tf-entity-location)", shape: "square", label: "Объект" },
  location: { family: "location", glyph: "pin", color: "var(--tf-entity-location)", shape: "hex", label: "Место" },
  lore: { family: "lore", glyph: "book", color: "var(--tf-entity-lore)", shape: "diamond", label: "Знание" },
};

/** Специализация по стабильному визуальному ключу, НЕ по отображаемому названию.
 * Будущие шаблоны предметов задают state.visual_key, например "item:chest".
 * Неизвестный ключ или ключ не той категории безопасно возвращает базовый пресет.
 * Добавление нового вида предметов не требует править ни одну карту или компонент Token.
 */
export const VISUAL_VARIANTS: Record<string, MapVisualPreset> = {
  "item:chest": { ...MAP_PRESETS.item, glyph: "chest", label: "Сундук" },
  "item:weapon": { ...MAP_PRESETS.item, glyph: "sword", label: "Оружие" },
  "item:potion": { ...MAP_PRESETS.item, glyph: "flask", label: "Зелье" },
  "item:scroll": { ...MAP_PRESETS.item, glyph: "scroll", label: "Свиток" },
  "item:key": { ...MAP_PRESETS.item, glyph: "key", label: "Ключ" },
  "item:coin": { ...MAP_PRESETS.item, glyph: "coin", label: "Монеты" },
  "item:container": { ...MAP_PRESETS.item, glyph: "box", label: "Контейнер" },
  "landmark:altar": { ...MAP_PRESETS.landmark, glyph: "landmark", label: "Алтарь" },
  "landmark:torch": { ...MAP_PRESETS.landmark, glyph: "torch", label: "Факел" },
  "landmark:tree": { ...MAP_PRESETS.landmark, glyph: "tree", label: "Дерево" },
  "creature:undead": { ...MAP_PRESETS.creature, glyph: "shield", label: "Нежить" },
};

export function entityVisual(type: EntityType, key?: string | null): MapVisualPreset {
  const variant = key && Object.hasOwn(VISUAL_VARIANTS, key) ? VISUAL_VARIANTS[key] : null;
  return variant?.family === type ? variant : MAP_PRESETS[type];
}

export const EXIT_VISUALS: Record<SketchExit["kind"], MapVisualPreset> = {
  door: { family: "exit", glyph: "door", color: "var(--tf-entity-location)", shape: "square", label: "Дверь" },
  bars: { family: "exit", glyph: "bars", color: "var(--tf-entity-location)", shape: "square", label: "Решётка" },
  window: { family: "exit", glyph: "window", color: "var(--tf-entity-location)", shape: "square", label: "Окно" },
  arch: { family: "exit", glyph: "arch", color: "var(--tf-entity-location)", shape: "square", label: "Арка" },
  stairs: { family: "exit", glyph: "stairs", color: "var(--tf-entity-location)", shape: "square", label: "Лестница" },
  hatch: { family: "exit", glyph: "hatch", color: "var(--tf-entity-location)", shape: "square", label: "Люк" },
  gap: { family: "exit", glyph: "gap", color: "var(--tf-entity-location)", shape: "square", label: "Пролом" },
  passage: { family: "exit", glyph: "passage", color: "var(--tf-entity-location)", shape: "square", label: "Проход" },
};

export const FEATURE_VISUALS: Record<SketchFeature["kind"], MapVisualPreset> = {
  furniture: { family: "feature", glyph: "table", color: "var(--tf-accent)", shape: "square", label: "Мебель" },
  cover: { family: "feature", glyph: "shield", color: "var(--tf-muted)", shape: "square", label: "Укрытие" },
  hazard: { family: "feature", glyph: "alert", color: "var(--tf-ember)", shape: "square", label: "Опасность" },
  light: { family: "feature", glyph: "torch", color: "var(--tf-accent)", shape: "square", label: "Источник света" },
  object: { family: "feature", glyph: "box", color: "var(--tf-patina)", shape: "square", label: "Объект" },
  nature: { family: "feature", glyph: "nature", color: "var(--tf-patina)", shape: "square", label: "Природный объект" },
};
