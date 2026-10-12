import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AudioState } from "../lib/types";
import { prepareMusic, primeMusic, type MusicDeck, type PreparedMusic } from "./music";
import { SoundMixer } from "./sound";

vi.mock("./music", () => ({ prepareMusic: vi.fn(), primeMusic: vi.fn() }));
vi.mock("../lib/api", () => ({ getToken: () => "token" }));

function node() {
  return { connect: vi.fn(), disconnect: vi.fn(), gain: {
    setValueAtTime: vi.fn(), setTargetAtTime: vi.fn(), cancelScheduledValues: vi.fn(),
  } };
}
class FakeContext {
  currentTime = 10;
  state = "running";
  destination = {};
  createGain = vi.fn(node);
  createBufferSource = vi.fn();
  decodeAudioData = vi.fn();
  close = vi.fn(async () => {});
}
function prepared(): PreparedMusic {
  return {
    element: { currentTime: 0, duration: 600, play: vi.fn(async () => {}) } as unknown as HTMLAudioElement,
    source: node() as unknown as MediaElementAudioSourceNode,
    gain: node() as unknown as GainNode,
    dispose: vi.fn(),
  };
}
const state = (id = "tta_camp"): AudioState => ({
  enabled: true, v: 1, now: 105,
  music: { id, title: id, layer: "music", url: `/api/audio/${id}`, gain_db: -3, since: 35 },
});

describe("воспроизведение музыки сцены", () => {
  let mixer: SoundMixer;
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(100_000);
    vi.stubGlobal("AudioContext", FakeContext);
    vi.clearAllMocks();
    vi.mocked(prepareMusic).mockReset();
    vi.mocked(primeMusic).mockReset();
    vi.mocked(primeMusic).mockImplementation(() => ({
      decks: [0, 1].map(() => ({
        element: { pause: vi.fn(), removeAttribute: vi.fn(), load: vi.fn() }, source: node(),
      })) as unknown as MusicDeck[], ready: Promise.resolve(),
    }));
    mixer = new SoundMixer();
  });
  afterEach(() => {
    mixer.stop();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("начинает с позиции сервера, подключает громкость и не декодирует музыку в AudioBuffer", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    await mixer.apply(state());
    await mixer.unlock();
    expect(music.element.currentTime).toBe(70);
    expect(music.element.play).toHaveBeenCalledOnce();
    const ctx = vi.mocked(prepareMusic).mock.calls[0][0] as unknown as FakeContext;
    expect(ctx.createBufferSource).not.toHaveBeenCalled();
    expect(ctx.decodeAudioData).not.toHaveBeenCalled();
    expect(music.gain.connect).toHaveBeenCalled();
    expect(music.gain.gain.setTargetAtTime).toHaveBeenCalledWith(expect.any(Number), 10, 3.5 / 3);
    await mixer.apply({ ...state(), v: 2 });
    expect(prepareMusic).toHaveBeenCalledOnce();
    mixer.stop();
    expect(music.dispose).toHaveBeenCalledOnce();
  });

  it("плавно меняет дорожку и освобождает старую после перехода", async () => {
    const first = prepared(), second = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    await mixer.unlock();
    await mixer.apply(state());
    await mixer.apply(state("tta_forest"));
    expect(first.gain.gain.setTargetAtTime).toHaveBeenLastCalledWith(0, 10, 3.5 / 3);
    expect(first.dispose).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(4000);
    expect(first.dispose).toHaveBeenCalledOnce();
    expect(second.dispose).not.toHaveBeenCalled();
  });

  it("отмена загрузки при выключении звука не превращается в ошибку", async () => {
    vi.mocked(prepareMusic).mockImplementationOnce(async (_ctx, _url, _token, signal) =>
      new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason))));
    await mixer.unlock();
    const pending = mixer.apply(state());
    await mixer.apply({ ...state(), enabled: false });
    await pending;
    expect(mixer.error).toBeNull();
  });

  it("уход из игры освобождает обе дорожки во время плавного перехода", async () => {
    const first = prepared(), second = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    await mixer.unlock();
    await mixer.apply(state());
    await mixer.apply(state("tta_forest"));
    mixer.stop();
    expect(first.dispose).toHaveBeenCalledOnce();
    expect(second.dispose).toHaveBeenCalledOnce();
  });

  it("после отказа autoplay снова предлагает разблокировку и позволяет повторить нажатие", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    await mixer.apply(state());
    vi.mocked(primeMusic).mockReturnValueOnce({ decks: [],
      ready: Promise.reject(new DOMException("blocked", "NotAllowedError")),
    });
    await expect(mixer.unlock()).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(mixer.unlocked).toBe(false);
    await mixer.unlock();
    expect(mixer.unlocked).toBe(true);
    expect(music.element.play).toHaveBeenCalledOnce();
  });

  it("при быстрой третьей смене переиспользует старый элемент без накопления дорожек", async () => {
    const first = prepared(), second = prepared(), third = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(first).mockResolvedValueOnce(second).mockResolvedValueOnce(third);
    await mixer.unlock();
    await mixer.apply(state());
    await mixer.apply(state("tta_forest"));
    await mixer.apply(state("tta_dungeon"));
    expect(first.dispose).toHaveBeenCalledOnce();
    const calls = vi.mocked(prepareMusic).mock.calls;
    expect(calls[0][4]).toBe(calls[2][4]);
    expect(calls[0][4]).not.toBe(calls[1][4]);
    mixer.stop();
    expect(second.dispose).toHaveBeenCalledOnce();
    expect(third.dispose).toHaveBeenCalledOnce();
  });
});
