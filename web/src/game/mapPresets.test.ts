import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import type { EntityType } from "../lib/types";
import { Token } from "./GridBoard";
import { MAP_GLYPHS, MapGlyph } from "./MapGlyph";
import { entityVisual, EXIT_VISUALS, FEATURE_VISUALS, MAP_PRESETS, VISUAL_VARIANTS } from "./mapPresets";

const TYPES: EntityType[] = ["hero", "creature", "npc", "item", "landmark", "location", "lore"];

describe("каталог визуальных элементов карты", () => {
  it("у каждого типа и элемента есть векторная иконка и читаемый стиль", () => {
    const visuals = [...Object.values(MAP_PRESETS), ...Object.values(VISUAL_VARIANTS),
      ...Object.values(EXIT_VISUALS), ...Object.values(FEATURE_VISUALS)];
    for (const visual of visuals) {
      expect(MAP_GLYPHS[visual.glyph]?.length).toBeGreaterThan(0);
      expect(visual.color).toMatch(/^var\(--tf-/);
      expect(visual.label).not.toBe("");
    }
    expect(TYPES.map((type) => entityVisual(type).family)).toEqual(TYPES);
    expect(new Set(TYPES.map((type) => entityVisual(type).shape)).size).toBeGreaterThan(2);
  });

  it("специализация предметов определяется только ключом, а не названием", () => {
    expect(entityVisual("item", "item:chest").glyph).toBe("chest");
    expect(entityVisual("item", "item:potion").glyph).toBe("flask");
    expect(entityVisual("item", "item:weapon").glyph).toBe("sword");
    expect(entityVisual("item", "item:not-installed")).toBe(MAP_PRESETS.item);
    expect(entityVisual("item", "creature:undead")).toBe(MAP_PRESETS.item);
    expect(entityVisual("creature", "item:potion")).toBe(MAP_PRESETS.creature);
    expect(entityVisual("item", "__proto__")).toBe(MAP_PRESETS.item);
    expect(entityVisual("item", null)).toBe(MAP_PRESETS.item);
  });

  it("визуальные ключи предметов можно использовать как метаданные шаблона", () => {
    const keys = ["item:chest", "item:weapon", "item:potion", "item:scroll", "item:key", "item:coin", "item:container"];
    for (const key of keys) {
      expect(entityVisual("item", key).family).toBe("item");
      expect(entityVisual("item", key)).toBe(VISUAL_VARIANTS[key]);
      expect(entityVisual("creature", key)).toBe(MAP_PRESETS.creature);
    }
    expect(entityVisual("item", "item:custom-not-yet-installed")).toBe(MAP_PRESETS.item);
  });

  it("один SVG-рендерер рисует пресеты без эмодзи и шрифтовых значков", () => {
    const markup = renderToStaticMarkup(createElement(Token, {
      cx: 10, cy: 12, size: 20, visual: entityVisual("item", "item:chest"),
      ariaLabel: "Сундук", selected: true,
    }));
    expect(markup).toContain('data-map-glyph="chest"');
    expect(markup).toContain("Сундук");
    expect(markup).toContain("<path");
    const icon = renderToStaticMarkup(createElement(MapGlyph, { name: "door", width: 20, height: 20 }));
    expect(icon).toContain("viewBox");
  });
});
