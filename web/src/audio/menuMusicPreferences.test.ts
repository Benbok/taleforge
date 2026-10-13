import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { useMenuMusicPreferences } from "./menuMusicPreferences";

vi.mock("../lib/api", () => ({ api: vi.fn() }));

const user = (id: string, enabled = true, volume = 0.2) => ({
  id, name: id, platform_role: "player" as const, menu_music: { enabled, volume },
});

describe("сохраняемые настройки темы меню", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api).mockReset();
    useMenuMusicPreferences.getState().bindUser(null);
  });
  afterEach(() => vi.useRealTimers());

  it("берёт настройки из аккаунта и объединяет быстрые изменения в один PATCH", async () => {
    vi.mocked(api).mockResolvedValue({ enabled: true, volume: 0.8 });
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ volume: 0.4 });
    useMenuMusicPreferences.getState().update({ volume: 0.6 });
    useMenuMusicPreferences.getState().update({ volume: 0.8 });
    expect(useMenuMusicPreferences.getState().prefs.volume).toBe(0.8);
    await vi.advanceTimersByTimeAsync(249);
    expect(api).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(api).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledWith("/api/me/menu-music", { method: "PATCH", body: { volume: 0.8 } });
    await vi.runAllTimersAsync();
    expect(useMenuMusicPreferences.getState().saveState).toBe("saved");
  });

  it("ждёт завершения PATCH и не откатывает более новый локальный выбор", async () => {
    let resolve!: (v: { enabled: boolean; volume: number }) => void;
    vi.mocked(api).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    vi.mocked(api).mockResolvedValueOnce({ enabled: false, volume: 0.2 });
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ volume: 0.4 });
    await vi.advanceTimersByTimeAsync(250);
    useMenuMusicPreferences.getState().update({ enabled: false });
    await vi.advanceTimersByTimeAsync(250);
    expect(api).toHaveBeenCalledOnce();
    resolve({ enabled: true, volume: 0.4 });
    await Promise.resolve();
    expect(api).toHaveBeenCalledTimes(2);
    expect(useMenuMusicPreferences.getState().prefs).toEqual({ enabled: false, volume: 0.4 });
  });

  it("ошибка оставляет выбор и retry повторяет последний PATCH", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ enabled: false, volume: 0.2 });
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ enabled: false });
    await vi.advanceTimersByTimeAsync(250);
    await Promise.resolve();
    expect(useMenuMusicPreferences.getState().saveState).toBe("error");
    expect(useMenuMusicPreferences.getState().prefs.enabled).toBe(false);
    useMenuMusicPreferences.getState().retry();
    await vi.advanceTimersByTimeAsync(250);
    expect(api).toHaveBeenCalledTimes(2);
    expect(useMenuMusicPreferences.getState().saveState).toBe("saved");
  });

  it("игнорирует поздний ответ старого аккаунта", async () => {
    let resolve!: (v: { enabled: boolean; volume: number }) => void;
    vi.mocked(api).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ volume: 0.9 });
    await vi.advanceTimersByTimeAsync(250);
    useMenuMusicPreferences.getState().bindUser(user("u2", false, 0.5));
    resolve({ enabled: true, volume: 0.9 });
    await Promise.resolve();
    expect(useMenuMusicPreferences.getState().userId).toBe("u2");
    expect(useMenuMusicPreferences.getState().prefs).toEqual({ enabled: false, volume: 0.5 });
  });

  it("после смены аккаунта дописывает pending PATCH после старого запроса", async () => {
    let resolve!: (v: { enabled: boolean; volume: number }) => void;
    vi.mocked(api)
      .mockImplementationOnce(() => new Promise(r => { resolve = r; }))
      .mockResolvedValueOnce({ enabled: false, volume: 0.6 });
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ volume: 0.9 });
    await vi.advanceTimersByTimeAsync(250);
    useMenuMusicPreferences.getState().bindUser(user("u2"));
    useMenuMusicPreferences.getState().update({ volume: 0.6, enabled: false });
    await vi.advanceTimersByTimeAsync(250);
    expect(api).toHaveBeenCalledOnce();
    resolve({ enabled: true, volume: 0.9 });
    await Promise.resolve();
    expect(api).toHaveBeenCalledTimes(2);
    expect(api).toHaveBeenLastCalledWith("/api/me/menu-music", {
      method: "PATCH", body: { volume: 0.6, enabled: false },
    });
  });

  it("после ошибки первого PATCH повторно сохраняет остальные локальные поля", async () => {
    vi.mocked(api)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ enabled: false, volume: 0.2 })
      .mockResolvedValueOnce({ enabled: false, volume: 0.8 });
    useMenuMusicPreferences.getState().bindUser(user("u1"));
    useMenuMusicPreferences.getState().update({ volume: 0.8 });
    await vi.advanceTimersByTimeAsync(250);
    await Promise.resolve();
    useMenuMusicPreferences.getState().update({ enabled: false });
    await vi.advanceTimersByTimeAsync(250);
    await Promise.resolve();
    expect(api).toHaveBeenCalledTimes(2);
    expect(api).toHaveBeenLastCalledWith("/api/me/menu-music", {
      method: "PATCH", body: { volume: 0.8, enabled: false },
    });
    expect(useMenuMusicPreferences.getState().saveState).toBe("error");
  });
});
