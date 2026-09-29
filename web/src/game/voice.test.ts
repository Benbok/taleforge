import { describe, expect, it } from "vitest";
import { clock, micError, pickMime } from "./voice";

describe("голосовые реплики", () => {
  it("выбирает формат, который умеет браузер", () => {
    expect(pickMime(() => true)).toBe("audio/webm;codecs=opus");
    expect(pickMime((t) => t === "audio/mp4")).toBe("audio/mp4"); // Safari
    expect(pickMime(() => false)).toBeUndefined();
  });

  it("длительность записи — минуты и секунды", () => {
    expect(clock(7.4)).toBe("0:07");
    expect(clock(83)).toBe("1:23");
  });

  it("объясняет, почему микрофон не включился", () => {
    expect(micError(new DOMException("x", "NotAllowedError"))).toMatch(/разрешите его/);
    expect(micError(new DOMException("x", "NotFoundError"))).toMatch(/не найден/);
  });
});
