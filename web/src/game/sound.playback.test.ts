import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AudioState, AudioTrack } from "../lib/types";
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
    element: {
      currentTime: 0, duration: 600, play: vi.fn(async () => {}), pause: vi.fn(),
    } as unknown as HTMLAudioElement,
    source: node() as unknown as MediaElementAudioSourceNode,
    gain: node() as unknown as GainNode,
    dispose: vi.fn(),
  };
}
const state = (id = "tta_camp"): AudioState => ({
  enabled: true, v: 1, now: 105,
  music: { id, title: id, layer: "music", url: `/api/audio/${id}`, gain_db: -3, since: 35 },
});
const menu = (id = "menu_edge_of_the_world"): AudioTrack => ({
  id, title: "Edge of the World", layer: "music", url: `/api/menu-music/file?v=${id}`, gain_db: 0,
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

  it("громкость меню не зависит от игровых master/mute/music настроек", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    mixer.setPrefs({ master: 0, music: 0, muted: true });
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("menu");
    expect(music.gain.gain.setTargetAtTime).toHaveBeenCalledWith(0.2, 10, expect.any(Number));
    expect(mixer.menuStatus).toBe("playing");
  });

  it("переходы внутри кабинета не перезапускают тему, а возврат сохраняет позицию", async () => {
    const first = prepared(), scene = prepared(), secondMenu = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(first).mockResolvedValueOnce(scene).mockResolvedValueOnce(secondMenu);
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("menu");
    first.element.currentTime = 37;
    await mixer.setSurface("menu");
    expect(prepareMusic).toHaveBeenCalledOnce();
    await mixer.apply(state());
    await mixer.setSurface("scene");
    expect(first.gain.gain.setTargetAtTime).toHaveBeenCalledWith(0, 10, 0.5 / 3);
    await mixer.setSurface("menu");
    expect(secondMenu.element.currentTime).toBe(37);
  });

  it("отключённая сцена не подменяется темой меню", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("scene");
    await mixer.apply({ ...state(), enabled: false, music: null });
    expect(prepareMusic).not.toHaveBeenCalled();
    expect(mixer.music).toBeNull();
  });

  it("скрывает меню и возобновляет его с сохранённой позиции", async () => {
    const first = prepared(), second = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("menu");
    first.element.currentTime = 19;
    await mixer.setDocumentVisible(false);
    expect(first.gain.gain.setTargetAtTime).toHaveBeenCalledWith(0, 10, 0.15 / 3);
    expect(mixer.menuStatus).toBe("paused");
    await mixer.setDocumentVisible(true);
    expect(second.element.currentTime).toBe(19);
  });

  it("устаревшая загрузка не запускается после ухода с поверхности", async () => {
    let resolve!: (music: PreparedMusic) => void;
    vi.mocked(prepareMusic).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    const pending = mixer.setSurface("menu");
    await mixer.setSurface("silent");
    resolve(prepared());
    await pending;
    expect(vi.mocked(prepareMusic).mock.results[0].type).toBe("return");
    expect(mixer.menuStatus).not.toBe("playing");
  });

  it("после отказа autoplay сохраняет цель и повторяет запуск", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("menu");
    expect(mixer.menuStatus).toBe("locked");
    await mixer.unlock();
    expect(mixer.menuStatus).toBe("playing");
  });

  it("clearScene сохраняет разблокировку и тему, stop освобождает всё", async () => {
    const music = prepared();
    vi.mocked(prepareMusic).mockResolvedValueOnce(music);
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    await mixer.setSurface("menu");
    mixer.clearScene();
    expect(mixer.unlocked).toBe(true);
    expect(mixer.menuStatus).toBe("playing");
    mixer.stop();
    expect(mixer.unlocked).toBe(false);
    expect(music.dispose).toHaveBeenCalledOnce();
  });

  it("эффекты на menu и silent не звучат", async () => {
    await mixer.unlock();
    await mixer.setSurface("menu");
    await expect(mixer.cue([state().music!])).resolves.toBeUndefined();
    await mixer.setSurface("silent");
    await expect(mixer.cue([state().music!])).resolves.toBeUndefined();
  });

  it("очистка menu metadata не отменяет начатую загрузку сцены", async () => {
    let resolve!: (music: PreparedMusic) => void;
    vi.mocked(prepareMusic).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    await mixer.unlock();
    const scene = mixer.apply(state());
    await Promise.resolve();
    const pending = mixer.setMenuMusic(null, { enabled: true, volume: 0.2 });
    resolve(prepared());
    await Promise.all([scene, pending]);
    expect(mixer.music?.id).toBe("tta_camp");
  });

  it("clearScene не оставляет загрузку меню в состоянии loading", async () => {
    let resolve!: (music: PreparedMusic) => void;
    vi.mocked(prepareMusic).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    await mixer.unlock();
    await mixer.setMenuMusic(menu(), { enabled: true, volume: 0.2 });
    const pending = mixer.setSurface("menu");
    await Promise.resolve();
    mixer.clearScene();
    resolve(prepared());
    await pending;
    expect(mixer.menuStatus).toBe("playing");
  });

  it("вычисляет позицию сцены после завершения загрузки", async () => {
    let resolve!: (music: PreparedMusic) => void;
    vi.mocked(prepareMusic).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    await mixer.apply(state());
    const pending = mixer.unlock();
    for (let i = 0; i < 5 && !resolve; i++) await Promise.resolve();
    vi.setSystemTime(100_012_000);
    const music = prepared();
    resolve(music);
    await pending;
    expect(music.element.currentTime).toBe(382);
  });

  it("не запускает вторую загрузку для одинакового pending состояния сцены", async () => {
    let resolve!: (music: PreparedMusic) => void;
    vi.mocked(prepareMusic).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    await mixer.unlock();
    const first = mixer.apply(state());
    await Promise.resolve();
    const second = mixer.apply(state());
    resolve(prepared());
    await Promise.all([first, second]);
    expect(prepareMusic).toHaveBeenCalledOnce();
  });
});
