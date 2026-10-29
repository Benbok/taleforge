import { beforeEach, describe, expect, it } from "vitest";
import {
  loadChatFontSize,
  loadSceneHeaderCollapsed,
  saveChatFontSize,
  saveSceneHeaderCollapsed,
  loadChatFontFamily,
  saveChatFontFamily,
} from "./scenePreferences";

describe("настройка свёрнутой шапки сцены", () => {
  beforeEach(() => localStorage.clear());

  it("uses false by default and persists a valid boolean", () => {
    expect(loadSceneHeaderCollapsed()).toBe(false);
    saveSceneHeaderCollapsed(true);
    expect(loadSceneHeaderCollapsed()).toBe(true);
    saveSceneHeaderCollapsed(false);
    expect(loadSceneHeaderCollapsed()).toBe(false);
  });

  it("ignores malformed storage values", () => {
    localStorage.setItem("tf_scene_header_collapsed", "broken");
    expect(loadSceneHeaderCollapsed()).toBe(false);
  });
});

describe("настройка размера шрифта чата", () => {
  beforeEach(() => localStorage.clear());

  it("uses medium by default and persists small/medium/large", () => {
    expect(loadChatFontSize()).toBe("medium");
    saveChatFontSize("small");
    expect(loadChatFontSize()).toBe("small");
    saveChatFontSize("large");
    expect(loadChatFontSize()).toBe("large");
    saveChatFontSize("medium");
    expect(loadChatFontSize()).toBe("medium");
  });

  it("ignores malformed font size values", () => {
    localStorage.setItem("tf_chat_font_size", "huge");
    expect(loadChatFontSize()).toBe("medium");
  });
});
describe("настройка стиля шрифта чата (книжный / экранный)", () => {
  beforeEach(() => localStorage.clear());

  it("uses serif by default and persists serif/sans", () => {
    expect(loadChatFontFamily()).toBe("serif");
    saveChatFontFamily("sans");
    expect(loadChatFontFamily()).toBe("sans");
    saveChatFontFamily("serif");
    expect(loadChatFontFamily()).toBe("serif");
  });

  it("ignores malformed font family values", () => {
    localStorage.setItem("tf_chat_font_family", "comic-sans");
    expect(loadChatFontFamily()).toBe("serif");
  });
});
