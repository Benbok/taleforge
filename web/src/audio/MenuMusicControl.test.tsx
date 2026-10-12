import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import MenuMusicControl from "./MenuMusicControl";
import { useMenuMusicPreferences } from "./menuMusicPreferences";

const fakeSound = vi.hoisted(() => ({
  audioSurface: "menu" as const,
  menuTheme: { id: "menu_edge_of_the_world", title: "Edge of the World", layer: "music", url: "/theme", gain_db: 0 } as {
    id: string; title: string; layer: string; url: string; gain_db: number;
  } | null,
  menuStatus: "locked" as string,
  menuError: null as string | null,
  unlocked: false,
  unlock: vi.fn(async () => {}),
}));
vi.mock("../game/sound", () => ({ useSound: () => fakeSound }));

describe("компактный контрол темы меню", () => {
  beforeEach(() => {
    fakeSound.audioSurface = "menu";
    fakeSound.menuTheme = { id: "menu_edge_of_the_world", title: "Edge of the World", layer: "music", url: "/theme", gain_db: 0 };
    fakeSound.menuStatus = "locked";
    fakeSound.menuError = null;
    fakeSound.unlocked = false;
    fakeSound.unlock.mockClear();
    useMenuMusicPreferences.setState({ userId: "u1", prefs: { enabled: true, volume: 0.2 }, saveState: "saved" });
  });
  afterEach(() => cleanup());

  it("разблокирует звук непосредственно нажатием", async () => {
    render(<MenuMusicControl />);
    fireEvent.click(screen.getByRole("button", { name: "Включить музыку" }));
    expect(fakeSound.unlock).toHaveBeenCalledOnce();
  });

  it("скрывается без метаданных темы", () => {
    fakeSound.menuTheme = null;
    render(<MenuMusicControl />);
    expect(screen.queryByRole("button", { name: /музык/ })).toBeNull();
  });

  it("оставляет повтор после ошибки воспроизведения", () => {
    fakeSound.menuStatus = "error";
    fakeSound.unlocked = true;
    render(<MenuMusicControl />);
    fireEvent.click(screen.getByRole("button", { name: "Включить музыку" }));
    expect(fakeSound.unlock).toHaveBeenCalledOnce();
  });
});
