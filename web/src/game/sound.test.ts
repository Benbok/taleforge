import { describe, expect, it } from "vitest";
import { suggestId } from "../admin/AudioSection";
import { useGame } from "../stores/game";
import { dbToGain, DEFAULT_PREFS, loopOffset, parsePrefs, untilBar } from "./sound";

describe("звук сцены", () => {
  it("петля стартует с той же позиции, что у остальных", () => {
    expect(loopOffset(0, 38.4)).toBe(0);
    expect(loopOffset(40, 38.4)).toBeCloseTo(1.6);
    expect(loopOffset(-1, 10)).toBeCloseTo(9); // часы браузера чуть впереди сервера
    expect(loopOffset(5, 0)).toBe(0);
  });

  it("ритм ждёт начала такта мелодии", () => {
    // 100 bpm, такт 4/4 = 2.4 с
    expect(untilBar(0, 100)).toBe(0);
    expect(untilBar(1.4, 100)).toBeCloseTo(1.0);
    expect(untilBar(2.4, 100)).toBe(0);
  });

  it("громкость в децибелах", () => {
    expect(dbToGain(0)).toBe(1);
    expect(dbToGain(-6)).toBeCloseTo(0.501, 2);
  });

  it("настройки игрока читаются из браузера и не ломаются мусором", () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs("{oops")).toEqual(DEFAULT_PREFS);
    expect(parsePrefs('{"muted":true,"music":0.4,"rhythm":7}')).toMatchObject({ muted: true, music: 0.4, rhythm: 1 });
  });

  it("id трека из имени файла", () => {
    expect(suggestId("Mel Rest.ogg", [])).toBe("mel_rest");
    expect(suggestId("Гроза.ogg", ["track"])).toBe("track_2");
  });

  it("состояние звука приходит в снимке и событием", () => {
    const layers = { music: null, rhythm: null, ambience: null };
    useGame.getState().apply({ type: "audio.state", campaign_id: "c", seq: null, payload: { enabled: true, v: 3, now: 1, layers, cues: [] } });
    expect(useGame.getState().audio).toEqual({ enabled: true, v: 3, now: 1, layers });
  });
});
