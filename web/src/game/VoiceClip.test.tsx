import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { useGame } from "../stores/game";

// Загрузка записи — управляемое обещание: можно задержать первую и отдать вторую раньше.
const pending = new Map<string, (url: string) => void>();
vi.mock("./voice", () => ({
  claimAutoplay: (() => {
    const seen = new Set<string>();
    return (id: string) => (seen.has(id) ? false : (seen.add(id), true));
  })(),
  clock: (s: number) => String(Math.round(s)),
  voiceUrl: (_c: string, id: string) => new Promise<string>((ok) => pending.set(id, ok)),
}));
vi.mock("./sound", () => ({ sound: { duck: () => {} } }));

const clip = (id: string) => ({ id, mime: "audio/ogg", duration: 1 });
const played: string[] = [];
const audios: FakeAudio[] = [];
class FakeAudio {
  src: string;
  currentTime = 0;
  ended = false;
  onended: (() => void) | null = null;
  onplay: (() => void) | null = null;
  onpause: (() => void) | null = null;
  ontimeupdate: (() => void) | null = null;
  constructor(src: string) {
    this.src = src;
    audios.push(this);
  }
  play() {
    played.push(this.src);
    this.onplay?.();
    return Promise.resolve();
  }
  pause() {
    played.push(`pause:${this.src}`);
    this.onpause?.();
  }
}

beforeEach(() => {
  vi.stubGlobal("Audio", FakeAudio);
  useGame.setState({ snapshot: { campaign: { id: "c1" } } } as never);
});

afterEach(() => {
  cleanup();
  pending.clear();
  played.length = 0;
  audios.length = 0;
  vi.unstubAllGlobals();
});

it("автозапуски нескольких сообщений идут по очереди, пока первая запись ещё грузится", async () => {
  const { default: VoiceClip } = await import("./VoiceClip");
  render(
    <>
      <VoiceClip clips={[clip("intro-1")]} autoPlay />
      <VoiceClip clips={[clip("story-1")]} autoPlay />
    </>,
  );
  // второе сообщение ждёт в очереди и не начинает грузиться, пока звучит первое
  expect(pending.has("story-1")).toBe(false);
  await act(async () => pending.get("intro-1")?.("url:intro-1"));
  expect(played).toEqual(["url:intro-1"]);
  // первое доиграло — очередь идёт дальше, второе звучит с начала
  await act(async () => audios.find((a) => a.src === "url:intro-1")?.onended?.());
  await act(async () => pending.get("story-1")?.("url:story-1"));
  expect(played).toEqual(["url:intro-1", "url:story-1"]);
});
