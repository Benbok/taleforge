import { describe, expect, it } from "vitest";
import { sceneLighting } from "./scenePresentation";

describe("атмосфера сцены", () => {
  it("uses a restrained glow for light mode and scene preset", () => {
    expect(sceneLighting({ preset: "coast", period: "day", weather: null, illustration_key: null }, "light", false)).toEqual({
      "--tf-scene-glow": "#5fae9f",
      "--tf-scene-glow-opacity": "0.060",
      "--tf-scene-edge": "transparent",
      "--tf-scene-edge-opacity": "0",
    });
  });

  it("deepens night atmosphere and adds a combat edge", () => {
    const vars = sceneLighting({ preset: "crypt", period: "night", weather: "fog", illustration_key: null }, "dark", true);
    expect(vars["--tf-scene-glow"]).toBe("#8c789a");
    expect(vars["--tf-scene-glow-opacity"]).toBe("0.105");
    expect(vars["--tf-scene-edge"]).toBe("#c4553f");
    expect(vars["--tf-scene-edge-opacity"]).toBe("0.08");
  });
});
