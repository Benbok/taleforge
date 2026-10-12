import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SoundControl from "./SoundControl";
import { useGame } from "../stores/game";

const fakeSound = vi.hoisted(() => ({
  unlocked: true,
  prefs: { muted: false, master: 0.8, music: 1, sfx: 1 },
  setPrefs: vi.fn(),
  unlock: vi.fn(async () => {}),
  error: null as string | null,
}));

vi.mock("./sound", async () => {
  const actual = await vi.importActual<typeof import("./sound")>("./sound");
  return {
    ...actual,
    useSound: () => fakeSound,
  };
});

describe("SoundControl popover", () => {
  beforeEach(() => {
    fakeSound.unlocked = true;
    fakeSound.prefs = { muted: false, master: 0.8, music: 1, sfx: 1 };
    fakeSound.setPrefs.mockClear();
    fakeSound.unlock.mockClear();
    fakeSound.error = null;
    useGame.setState({
      audio: { enabled: true, v: 1, now: 100, music: { id: "track_1", title: "Ветер в руинах", layer: "music", url: "/track1", gain_db: 0 } },
      actions: [],
    });
  });

  afterEach(() => cleanup());

  it("не отображается, если звук выключен в кампании", () => {
    useGame.setState({ audio: null });
    const { container } = render(<SoundControl />);
    expect(container.firstChild).toBeNull();
  });

  it("показывает кнопку включения звука, если браузер ещё не разблокирован", () => {
    fakeSound.unlocked = false;
    render(<SoundControl />);
    expect(screen.getByRole("button", { name: /Включить звук/ })).toBeTruthy();
  });

  it("раскрывает всплывающую карточку с классом z-50 поверх стола и позволяет выключить звук", () => {
    render(<SoundControl />);
    const trigger = screen.getByRole("button", { name: "Звук сцены" });
    fireEvent.click(trigger);

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const heading = screen.getByText("Звук сцены");
    expect(heading).toBeTruthy();

    const popover = heading.closest(".absolute");
    expect(popover).toBeTruthy();
    expect(popover?.className).toContain("z-50");

    const muteBtn = screen.getByRole("button", { name: "Выключить" });
    fireEvent.click(muteBtn);
    expect(fakeSound.setPrefs).toHaveBeenCalledWith({ muted: true });
  });

  it("закрывает всплывающую карточку по повторному клику", () => {
    render(<SoundControl />);
    const trigger = screen.getByRole("button", { name: "Звук сцены" });
    fireEvent.click(trigger);
    expect(screen.getByText("Звук сцены")).toBeTruthy();

    fireEvent.click(trigger);
    expect(screen.queryByText("Звук сцены")).toBeNull();
  });
});
