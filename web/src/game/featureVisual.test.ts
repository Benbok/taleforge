import { expect, it } from "vitest";
import { overlayVisual } from "./mapPresets";

const glyph = (name: string, type: "item" | "landmark" = "landmark", key?: string) =>
  overlayVisual({ name, kind: "object", entity_type: type, visual_key: key }).glyph;

it("подбирает значок по названию, когда у предмета нет ключа рисунка", () => {
  expect(glyph("Роща молодых дубов и ясеней")).toBe("tree");
  expect(glyph("Яблоневый сад за плетнём")).toBe("tree");
  expect(glyph("Ивовый плетень вдоль огородов")).toBe("nature");
  expect(glyph("Поленница под навесом")).toBe("box");
  expect(glyph("Столб с дощечкой-указателем")).toBe("pin");
  expect(glyph("Сундук с замком")).toBe("chest");
  expect(glyph("Железный ключ", "item")).toBe("key");
});

it("значок по названию: «столб» не принимается за «стол», а «деревянный» за «дерево»", () => {
  expect(glyph("Деревянный сундук")).toBe("chest");
  expect(glyph("Дубовый стол")).toBe("table");
  expect(glyph("Столб")).toBe("pin");
});

it("без подходящих слов остаётся значок типа, а «столб» не принимается за «стол»", () => {
  expect(glyph("Мшистый придорожный камень")).toBe("landmark");
  expect(glyph("Оброненная хоббитская шапка", "item")).toBe("gem");
});

it("явный ключ рисунка сильнее названия", () => {
  expect(glyph("Старый дуб", "item", "item:chest")).toBe("chest");
  expect(glyph("Дуб", "landmark", "landmark:altar")).toBe("landmark");
});
