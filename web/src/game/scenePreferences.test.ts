import { beforeEach, describe, expect, it } from "vitest";
import {
  loadChatFontSize,
  loadSceneHeaderCollapsed,
  saveChatFontSize,
  saveSceneHeaderCollapsed,
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
