import { beforeEach, describe, expect, it } from "vitest";
import { loadSceneHeaderCollapsed, saveSceneHeaderCollapsed } from "./scenePreferences";

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
