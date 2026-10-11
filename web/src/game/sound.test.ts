import { describe, expect, it } from "vitest";
import { cueList, suggestId, titleOf } from "../admin/AudioSection";
import { useGame } from "../stores/game";
import { dbToGain, DEFAULT_PREFS, loopOffset, parsePrefs, SfxGate } from "./sound";

describe("звук сцены", () => {
  it("готовый эффект не повторяется и не играет после истечения срока или смены места", () => {
    const gate = new SfxGate();
    const scene = { mode: "free", round: 0, location: { id: "tower", name: "Башня" }, entities: [], turn: null } as const;
    const event = { event_id: "sp_first", request_id: "sp_first", asset_id: "sa_first",
      track: { id: "sa_first", title: "Гром", layer: "sfx", gain_db: -3, url: "/api/sound" },
      duration_seconds: 3, place_id: "tower", mode: "free", round: 0, now: 100, expires_at: 115 };
    gate.scene(scene);
    const valid = gate.accept(event, 100);
    expect(valid?.(101)).toBe(true);
    expect(gate.accept(event, 101)).toBeNull();
    expect(valid?.(116)).toBe(false);
    gate.scene({ ...scene, location: { id: "forest", name: "Лес" } });
    expect(valid?.(102)).toBe(false);
    expect(gate.accept({ ...event, event_id: "sp_wrong" }, 102)).toBeNull();
  });
  it("петля стартует с той же позиции, что у остальных", () => {
    expect(loopOffset(0, 38.4)).toBe(0);
    expect(loopOffset(40, 38.4)).toBeCloseTo(1.6);
    expect(loopOffset(-1, 10)).toBeCloseTo(9); // часы браузера чуть впереди сервера
    expect(loopOffset(5, 0)).toBe(0);
  });

  it("громкость в децибелах", () => {
    expect(dbToGain(0)).toBe(1);
    expect(dbToGain(-6)).toBeCloseTo(0.501, 2);
  });

  it("настройки игрока читаются из браузера и не ломаются мусором", () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs("{oops")).toEqual(DEFAULT_PREFS);
    expect(parsePrefs('{"muted":true,"music":0.4,"sfx":7}')).toMatchObject({ muted: true, music: 0.4, sfx: 1 });
  });

  it("id трека из имени файла", () => {
    expect(suggestId("Mel Rest.ogg", [])).toBe("mel_rest");
    expect(suggestId("Гроза.ogg", ["track"])).toBe("track_2");
  });

  it("название и события из карточки", () => {
    expect(titleOf("rolling_war_drums.mp3")).toBe("Rolling war drums");
    expect(cueList("crit")).toEqual(["crit"]);
    expect(cueList(["death", "secret"])).toEqual(["death", "secret"]);
    expect(cueList(null)).toEqual([]);
  });

  it("состояние звука приходит в снимке и событием", () => {
    useGame.getState().apply({ type: "audio.state", campaign_id: "c", seq: null, payload: { enabled: true, v: 3, now: 1, music: null, cues: [] } });
    expect(useGame.getState().audio).toEqual({ enabled: true, v: 3, now: 1, music: null });
  });
});
