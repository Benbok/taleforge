import { describe, expect, it } from "vitest";
import { channelOf, differentVoices } from "./VoiceChannels";

describe("каналы озвучки", () => {
  it("кампания до раздельных каналов: реплики общим голосом, текст выключен", () => {
    const st = { tts_provider: "gemini", tts_voice: "Kore" };
    expect(channelOf(st, "line")).toEqual({ enabled: true, provider: "gemini", voice: "Kore" });
    expect(channelOf(st, "text").enabled).toBe(false);
  });

  it("у каждого канала свой источник и голос", () => {
    const st = { tts_line_provider: "voicestudio", tts_line_voice: "clone01", tts_text_enabled: true, tts_text_provider: "gemini", tts_text_voice: "Aoede" };
    expect(channelOf(st, "line")).toEqual({ enabled: true, provider: "voicestudio", voice: "clone01" });
    expect(channelOf(st, "text")).toEqual({ enabled: true, provider: "gemini", voice: "Aoede" });
    expect(differentVoices(st)).toBe(true);
    expect(differentVoices({ ...st, tts_text_enabled: false })).toBe(false);
  });
});
