import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import AudioSettingsSection from "./AudioSettingsSection";
import { useMenuMusicPreferences } from "../audio/menuMusicPreferences";

const fakeSound = vi.hoisted(() => ({ menuTheme: { title: "Edge of the World" }, menuStatus: "playing", menuError: null }));
vi.mock("../game/sound", () => ({ useSound: () => fakeSound }));

describe("настройки звука приложения", () => {
  beforeEach(() => useMenuMusicPreferences.setState({ userId: "u1", prefs: { enabled: true, volume: 0.2 }, saveState: "saved" }));
  afterEach(() => cleanup());

  it("показывает точные настройки и сразу меняет slider", () => {
    render(<AudioSettingsSection />);
    expect(screen.getByText("Звук приложения")).toBeTruthy();
    expect(screen.getByText("Музыка главного меню")).toBeTruthy();
    expect(screen.getByText(/Edge of the World/)).toBeTruthy();
    const slider = screen.getByRole("slider", { name: "Громкость музыки меню" });
    expect(slider.getAttribute("min")).toBe("0");
    expect(slider.getAttribute("max")).toBe("100");
    expect(slider.getAttribute("step")).toBe("5");
    fireEvent.change(slider, { target: { value: "50" } });
    expect(useMenuMusicPreferences.getState().prefs.volume).toBe(0.5);
  });

  it("показывает ошибку сохранения и кнопку повтора", () => {
    useMenuMusicPreferences.setState({ saveState: "error" });
    render(<AudioSettingsSection />);
    expect(screen.getByText("Не удалось сохранить настройки музыки")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeTruthy();
  });
});
