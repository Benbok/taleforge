import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { prepareMusic, primeMusic } from "./music";

class FakeAudio extends EventTarget {
  static instances: FakeAudio[] = [];
  src = "";
  preload = "";
  loop = false;
  duration = 600;
  currentTime = 0;
  readyState = 0;
  play = vi.fn(async () => {});
  pause = vi.fn();
  load = vi.fn(() => {
    if (this.src) queueMicrotask(() => {
      this.readyState = 1;
      this.dispatchEvent(new Event("loadedmetadata"));
    });
  });
  removeAttribute(name: string) { if (name === "src") this.src = ""; }
  constructor() { super(); FakeAudio.instances.push(this); }
}

describe("длинная фоновая музыка", () => {
  const fetchMock = vi.fn();
  const revoke = vi.fn();
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const gain = { connect: vi.fn(), disconnect: vi.fn(), gain: {
    setValueAtTime: vi.fn(), setTargetAtTime: vi.fn(), cancelScheduledValues: vi.fn(),
  } };
  const ctx = { createMediaElementSource: vi.fn(() => source), createGain: vi.fn(() => gain) };

  beforeEach(() => {
    vi.clearAllMocks();
    FakeAudio.instances = [];
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:music"), revokeObjectURL: revoke });
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["mp3"], { type: "audio/mpeg" }) });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("разблокирует оба переиспользуемых элемента синхронно по нажатию", async () => {
    const primed = primeMusic(ctx as unknown as AudioContext);
    expect(FakeAudio.instances).toHaveLength(2);
    for (const element of FakeAudio.instances) expect(element.play).toHaveBeenCalledOnce();
    await primed.ready;
    const music = await prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret",
      new AbortController().signal, primed.decks[0]);
    expect(FakeAudio.instances).toHaveLength(2);
    expect(ctx.createMediaElementSource).toHaveBeenCalledTimes(2);
    music.dispose();
    const again = await prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret",
      new AbortController().signal, primed.decks[0]);
    expect(ctx.createMediaElementSource).toHaveBeenCalledTimes(2);
    again.dispose();
  });

  it("читает сжатый файл с авторизацией, без decodeAudioData, и освобождает его", async () => {
    const music = await prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret", new AbortController().signal);
    expect(fetchMock).toHaveBeenCalledWith("/api/audio/tta", expect.objectContaining({
      headers: { Authorization: "Bearer secret" },
    }));
    const element = FakeAudio.instances[0];
    expect(element.loop).toBe(true);
    expect(music.element.duration).toBe(600);
    music.dispose();
    music.dispose();
    expect(element.pause).toHaveBeenCalledTimes(1);
    expect(element.src).toBe("");
    expect(source.disconnect).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:music");
  });

  it("не создаёт проигрыватель, если сцену сменили во время скачивания", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementationOnce(async () => {
      controller.abort();
      return { ok: true, blob: async () => new Blob(["mp3"]) };
    });
    await expect(prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret", controller.signal))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(FakeAudio.instances).toHaveLength(0);
  });

  it("освобождает файл, если браузер не прочитал дорожку", async () => {
    class BrokenAudio extends FakeAudio {
      constructor() {
        super();
        this.load = vi.fn(() => {
          if (this.src) queueMicrotask(() => this.dispatchEvent(new Event("error")));
        });
      }
    }
    vi.stubGlobal("Audio", BrokenAudio);
    await expect(prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret", new AbortController().signal))
      .rejects.toThrow("аудио");
    expect(revoke).toHaveBeenCalledWith("blob:music");
  });

  it("ошибка загрузки сохраняет сообщение сервера", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "трек удалён" }) });
    await expect(prepareMusic(ctx as unknown as AudioContext, "/api/audio/tta", "secret", new AbortController().signal))
      .rejects.toThrow("трек удалён");
    expect(FakeAudio.instances).toHaveLength(0);
  });
});
