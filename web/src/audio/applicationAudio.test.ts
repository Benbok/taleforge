import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { ApplicationAudioCoordinator, audioSurfaceFor, installAutoUnlock, installVisibilityListener } from "./applicationAudioCoordinator";

vi.mock("../lib/api", () => ({ api: vi.fn() }));

const user = (id: string) => ({ id, name: id, platform_role: "player" as const, menu_music: { enabled: true, volume: 0.2 } });
const theme = { id: "menu_edge_of_the_world", title: "Edge of the World", layer: "music", url: "/api/menu-music/file?v=1", gain_db: 0 };

function mixer() {
  return { setSurface: vi.fn(async () => {}), setMenuMusic: vi.fn(async () => {}), stop: vi.fn() };
}

describe("поверхность звука приложения", () => {
  beforeEach(() => vi.mocked(api).mockReset());
  it.each([
    "/", "/admin", "/new", "/profile", "/worlds/w1", "/heroes/h1", "/c/c1/manage", "/c/c1/hero",
  ])("пускает тему в кабинете, админке и детализации миров: %s", (path) => {
    expect(audioSurfaceFor(path, true)).toBe("menu");
  });

  it.each(["/c/c1", "/c/c1?tab=chat"])("выбирает сцену только для игры: %s", (path) => {
    expect(audioSurfaceFor(path, true)).toBe("scene");
  });

  it.each(["/invite/t", "/unknown", "/c/c1/unknown"])("оставляет тишину на %s", (path) => {
    expect(audioSurfaceFor(path, true)).toBe("silent");
    expect(audioSurfaceFor(path, false)).toBe("silent");
  });

  it("пускает тему на экране логирования и в мирах анонимному пользователю", () => {
    expect(audioSurfaceFor("/", false)).toBe("menu");
    expect(audioSurfaceFor("/admin", false)).toBe("menu");
    expect(audioSurfaceFor("/worlds/echo-leviathans", false)).toBe("menu");
    expect(audioSurfaceFor("/c/c1", false)).toBe("silent");
  });

  it("пускает тему на странице логина для неавторизованного пользователя", async () => {
    vi.mocked(api).mockResolvedValue(theme);
    const m = mixer();
    const coordinator = new ApplicationAudioCoordinator(m);
    await coordinator.reconcile("/", null, { enabled: true, volume: 0.2 });
    expect(m.setSurface).toHaveBeenCalledWith("menu");
    expect(m.setMenuMusic).toHaveBeenCalledWith(theme, { enabled: true, volume: 0.2 });
  });

  it("пускает тему в админке для авторизованного пользователя", async () => {
    vi.mocked(api).mockResolvedValue(theme);
    const m = mixer();
    const coordinator = new ApplicationAudioCoordinator(m);
    await coordinator.reconcile("/admin", user("admin"), { enabled: true, volume: 0.2 });
    expect(m.setSurface).toHaveBeenCalledWith("menu");
    expect(m.setMenuMusic).toHaveBeenCalledWith(theme, { enabled: true, volume: 0.2 });
  });

  it("запрашивает метаданные темы один раз и не скачивает MP3", async () => {
    vi.mocked(api).mockResolvedValue(theme);
    const m = { setSurface: vi.fn(), setMenuMusic: vi.fn(async () => {}), stop: vi.fn() };
    const coordinator = new ApplicationAudioCoordinator(m);
    await coordinator.reconcile("/", user("u1"), { enabled: true, volume: 0.2 });
    await coordinator.reconcile("/profile", user("u1"), { enabled: true, volume: 0.2 });
    expect(api).toHaveBeenCalledOnce();
    expect(m.setMenuMusic).toHaveBeenLastCalledWith(theme, { enabled: true, volume: 0.2 });
  });

  it("не применяет позднюю тему после смены аккаунта", async () => {
    let firstResolve!: (value: typeof theme | null) => void;
    vi.mocked(api)
      .mockImplementationOnce(() => new Promise(resolve => { firstResolve = resolve; }))
      .mockResolvedValueOnce({ ...theme, id: "menu_second" });
    const m = { setSurface: vi.fn(), setMenuMusic: vi.fn(async () => {}), stop: vi.fn() };
    const coordinator = new ApplicationAudioCoordinator(m);
    const first = coordinator.reconcile("/", user("u1"), { enabled: true, volume: 0.2 });
    await Promise.resolve();
    const second = coordinator.reconcile("/", user("u2"), { enabled: false, volume: 0.5 });
    await Promise.resolve();
    firstResolve(null);
    await Promise.all([first, second]);
    await coordinator.reconcile("/profile", user("u2"), { enabled: false, volume: 0.5 });
    expect(m.setMenuMusic).toHaveBeenCalledTimes(2);
    expect(m.setMenuMusic).toHaveBeenLastCalledWith({ ...theme, id: "menu_second" }, { enabled: false, volume: 0.5 });
  });

  it("выход во время запроса останавливает звук и не применяет тему устаревшего пользователя", async () => {
    let resolve!: (value: typeof theme) => void;
    vi.mocked(api).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const m = mixer();
    const coordinator = new ApplicationAudioCoordinator(m);
    const pending = coordinator.reconcile("/", user("u1"), { enabled: true, volume: 0.2 });
    await Promise.resolve();
    await coordinator.reconcile("/unknown", null, { enabled: true, volume: 0.2 });
    resolve(theme);
    await pending;
    expect(m.stop).toHaveBeenCalledOnce();
    expect(m.setMenuMusic).not.toHaveBeenCalled();
  });

  it("передаёт скрытие вкладки только микшеру меню", () => {
    const m = { setDocumentVisible: vi.fn() };
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    const remove = installVisibilityListener(m);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(m.setDocumentVisible).toHaveBeenCalledWith(false);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(m.setDocumentVisible).toHaveBeenLastCalledWith(true);
    remove();
  });

  it("не применяет устаревшие настройки после более нового reconcile", async () => {
    vi.mocked(api).mockResolvedValue(theme);
    const m = mixer();
    const coordinator = new ApplicationAudioCoordinator(m);
    const first = coordinator.reconcile("/", user("u1"), { enabled: true, volume: 0.2 });
    const second = coordinator.reconcile("/", user("u1"), { enabled: true, volume: 0.8 });
    await Promise.all([first, second]);
    expect(m.setMenuMusic).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledOnce();
    expect(m.setMenuMusic).toHaveBeenCalledWith(theme, { enabled: true, volume: 0.8 });
  });
});

describe("автоматическая разблокировка темы меню", () => {
  it("разблокирует звук сразу при монтировании, если разрешено", () => {
    const unlock = vi.fn(async () => {});
    const remove = installAutoUnlock({ unlock, unlocked: false }, () => true);
    expect(unlock).toHaveBeenCalledOnce();
    remove();
  });

  it("не вызывает разблокировку, если условие не выполнено или звук уже разблокирован", () => {
    const unlock = vi.fn(async () => {});
    const remove1 = installAutoUnlock({ unlock, unlocked: false }, () => false);
    expect(unlock).not.toHaveBeenCalled();
    remove1();

    const remove2 = installAutoUnlock({ unlock, unlocked: true }, () => true);
    expect(unlock).not.toHaveBeenCalled();
    remove2();
  });

  it("разблокирует звук по взаимодействию пользователя", () => {
    const unlock = vi.fn(async () => {});
    const mixerObj = { unlock, unlocked: false };
    const remove = installAutoUnlock(mixerObj, () => true);
    expect(unlock).toHaveBeenCalledOnce();

    unlock.mockClear();
    window.dispatchEvent(new Event("pointerdown"));
    expect(unlock).toHaveBeenCalledOnce();

    unlock.mockClear();
    mixerObj.unlocked = true;
    window.dispatchEvent(new Event("keydown"));
    expect(unlock).not.toHaveBeenCalled();

    remove();
  });
});
