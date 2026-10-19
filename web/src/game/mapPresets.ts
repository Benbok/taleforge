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
  effect: { family: "effect", glyph: "alert", color: "var(--tf-ember)", shape: "diamond", label: "Эффект" },
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

export type FeatureForm = "table" | "bench" | "bed" | "counter" | "shelf" | "barrel" | "crate" | "chest"
  | "hearth" | "torch" | "altar" | "pillar" | "rock" | "rubble" | "tree" | "shrub" | "reeds"
  | "crystal" | "bones" | "net" | "crane" | "mooring" | "glow" | "lichen" | "nest"
  | "chair" | "desk" | "wardrobe" | "weapon_rack" | "workbench" | "anvil" | "forge" | "cauldron"
  | "chandelier" | "brazier" | "statue" | "fountain" | "well" | "sarcophagus" | "tombstone"
  | "cart" | "cage" | "carpet" | "stump" | "log" | "mushrooms" | "sack"
  | "torture_table" | "tool_table" | "weapon_table" | "torture_chair" | "throne" | "defiled_throne"
  | "hazard" | "token";
export interface FeatureVisual extends MapVisualPreset { form: FeatureForm; }

/** Stable artwork keys. Legacy furniture without a specialised key is resolved below. */
export const FEATURE_VARIANTS: Record<string, FeatureVisual> = Object.fromEntries(
  (Object.entries({
    throne: ["furniture", "Трон"], defiled_throne: ["furniture", "Осквернённый трон"],
    torture_table: ["furniture", "Пыточный стол"], tool_table: ["furniture", "Инструментальный стол"],
    weapon_table: ["furniture", "Стол с оружием"], torture_chair: ["furniture", "Кресло для допросов"],
    table: ["furniture", "Стол"], bench: ["furniture", "Скамья"], bed: ["furniture", "Кровать"],
    counter: ["furniture", "Стойка"], shelf: ["furniture", "Стеллаж"], barrel: ["object", "Бочка"],
    crate: ["object", "Ящик"], chest: ["object", "Сундук"], hearth: ["light", "Очаг"], torch: ["light", "Свет"],
    altar: ["object", "Алтарь"], pillar: ["cover", "Колонна"], rock: ["cover", "Скала"],
    rubble: ["cover", "Обломки"], tree: ["nature", "Дерево"], shrub: ["nature", "Кустарник"],
    reeds: ["nature", "Камыш"], crystal: ["nature", "Кристаллы"], bones: ["object", "Кости"],
    net: ["object", "Сети"], crane: ["object", "Кран"], mooring: ["object", "Кнехт"],
    glow: ["light", "Мягкое свечение"], lichen: ["light", "Светящийся мох"], nest: ["nature", "Лёжка"],
    chair: ["furniture", "Стул"], desk: ["furniture", "Письменный стол"], wardrobe: ["furniture", "Шкаф"],
    weapon_rack: ["furniture", "Оружейная стойка"], workbench: ["furniture", "Верстак"],
    anvil: ["object", "Наковальня"], forge: ["light", "Кузнечный горн"], cauldron: ["object", "Котёл"],
    chandelier: ["light", "Люстра"], brazier: ["light", "Жаровня"], statue: ["cover", "Статуя"],
    fountain: ["object", "Фонтан"], well: ["object", "Колодец"], sarcophagus: ["cover", "Саркофаг"],
    tombstone: ["cover", "Надгробие"], cart: ["cover", "Телега"], cage: ["object", "Клетка"],
    carpet: ["furniture", "Ковёр"], stump: ["nature", "Пень"], log: ["nature", "Бревно"],
    mushrooms: ["nature", "Грибы"], sack: ["object", "Мешки"],
  }) as [FeatureForm, [SketchFeature["kind"], string]][])
    .map(([form, [kind, label]]) => [`feature:${form}`, { ...FEATURE_VISUALS[kind], form, label }]),
);

const DEFAULT_FEATURE_FORMS: Record<SketchFeature["kind"], FeatureForm> = {
  furniture: "table", cover: "rock", hazard: "hazard", light: "torch", object: "crate", nature: "shrub",
};

/** Resolve old furniture lacking a specific key; explicit specialised keys always win. */
function legacyFurnitureForm(name = ""): FeatureForm | undefined {
  const text = name.toLocaleLowerCase();
  if (/трон|throne/.test(text)) return /оскверн|проклят|defiled|cursed|corrupt/.test(text) ? "defiled_throne" : "throne";
  if (/desk/.test(text) || (/стол/.test(text) && /письмен/.test(text))) return "desk";
  const restraint = /пыт|допрос|torture|interrogation/.test(text);
  if (/кресл|стул|chair/.test(text) && restraint) return "torture_chair";
  if (/стойк|стеллаж|rack/.test(text) && /оруди|оруж|инструмент|weapon|tool/.test(text)) return "weapon_rack";
  if (/стол|table/.test(text)) {
    if (restraint) return "torture_table";
    if (/инструмент|tool|instrument/.test(text)) return "tool_table";
    if (/оруди|оруж|weapon/.test(text)) return "weapon_table";
  }
  return undefined;
}

export function featureVisual(feature: Pick<SketchFeature, "kind" | "visual_key" | "entity_type"> & { name?: string }): FeatureVisual {
  const key = feature.visual_key;
  if (feature.kind === "furniture" && (!key || key === "feature:table")) {
    const legacy = legacyFurnitureForm(feature.name);
    if (legacy) return FEATURE_VARIANTS[`feature:${legacy}`];
  }
  if (key && Object.hasOwn(FEATURE_VARIANTS, key)) return FEATURE_VARIANTS[key];
  // Materialised world objects keep the same trusted entity artwork used by map tokens.
  if (key && feature.entity_type && Object.hasOwn(VISUAL_VARIANTS, key)
    && VISUAL_VARIANTS[key].family === feature.entity_type) {
    return { ...entityVisual(feature.entity_type, key), form: "token" };
  }
  const kind = Object.hasOwn(FEATURE_VISUALS, feature.kind) ? feature.kind : "object";
  return { ...FEATURE_VISUALS[kind], form: DEFAULT_FEATURE_FORMS[kind] };
}
