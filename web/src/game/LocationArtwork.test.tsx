import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import LocationArtwork from "./LocationArtwork";

vi.mock("../lib/authedImage", () => ({ useAuthedImage: (url: string) => `blob:${url}` }));
const idle = { status: "idle", image_url: null as string | null, stale: false, enabled: true, can_generate: true, error: null };
const dialogMethods = ["showModal", "close"].map(key => [key, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, key)] as const);
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.unstubAllGlobals();
  for (const [key, descriptor] of dialogMethods) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, key, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, key);
  }
});

it("просмотр не запускает генерацию, явный клик создаёт и показывает картинку", async () => {
  const requests: { url: string; method: string }[] = [];
  let state = idle;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    requests.push({ url, method: init?.method ?? "GET" });
    if (init?.method === "POST") state = { ...idle, status: "ready", image_url: "/image/forest" };
    return new Response(JSON.stringify(state));
  }));
  render(<LocationArtwork campaignId="c" locationId="forest" name="Лес" />);
  const button = await screen.findByRole("button", { name: "Создать иллюстрацию" });
  expect(requests.every(r => r.method === "GET")).toBe(true);
  fireEvent.click(button);
  expect(await screen.findByRole("img", { name: "Иллюстрация локации «Лес»" })).toBeTruthy();
  expect(requests.filter(r => r.method === "POST")).toHaveLength(1);
});

it("участник видит сохранённую иллюстрацию без кнопки генерации", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...idle, status: "ready", image_url: "/image", can_generate: false }))));
  render(<LocationArtwork campaignId="c" locationId="forest" name="Лес" />);
  expect(await screen.findByRole("img")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^(Создать|Обновить) иллюстрацию$/ })).toBeNull();
});

it("поздний ответ предыдущей комнаты не заменяет иллюстрацию нового места", async () => {
  let resolveOld: (value: Response) => void = () => undefined;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("forest")) return new Promise<Response>(resolve => { resolveOld = resolve; });
    return new Response(JSON.stringify({ ...idle, status: "ready", image_url: "/image/port" }));
  }));
  const page = render(<LocationArtwork key="forest" campaignId="c" locationId="forest" name="Лес" />);
  page.rerender(<LocationArtwork key="port" campaignId="c" locationId="port" name="Порт" />);
  expect(await screen.findByRole("img", { name: "Иллюстрация локации «Порт»" })).toBeTruthy();
  resolveOld(new Response(JSON.stringify({ ...idle, status: "ready", image_url: "/image/forest" })));
  await waitFor(() => expect(screen.queryByRole("img", { name: "Иллюстрация локации «Лес»" })).toBeNull());
});

it("участник получает картинку, созданную другим пользователем, без перезахода", async () => {
  vi.useFakeTimers();
  let state = { ...idle, can_generate: false };
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state))));
  await act(async () => { render(<LocationArtwork campaignId="c" locationId="forest" name="Лес" />); });
  expect(screen.queryByRole("img")).toBeNull();
  state = { ...state, status: "ready", image_url: "/image/shared" };
  await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
  expect(screen.getByRole("img", { name: "Иллюстрация локации «Лес»" })).toBeTruthy();
});

it("после ошибки проверки ожидающей генерации продолжает получать статус", async () => {
  vi.useFakeTimers();
  let calls = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    calls++;
    if (calls === 2) throw new Error("connection lost");
    return new Response(JSON.stringify(calls === 1 ? { ...idle, status: "pending" } : { ...idle, status: "ready", image_url: "/image/recovered" }));
  }));
  await act(async () => { render(<LocationArtwork campaignId="c" locationId="forest" name="Лес" />); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(screen.getByRole("button", { name: "Повторить проверку" })).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByRole("img")).toBeTruthy();
});

it("открывает картинку внутри приложения и возвращает фокус после Escape", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...idle, status: "ready", image_url: "/image" }))));
  const parent = vi.fn();
  render(<div onKeyDown={parent}><LocationArtwork campaignId="c" locationId="forest" name="Лес" /></div>);
  const trigger = await screen.findByRole("button", { name: "Открыть иллюстрацию локации «Лес»" });
  expect(screen.queryByRole("link")).toBeNull();
  trigger.focus();
  const previousOverflow = document.body.style.overflow;
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Локация «Лес»" });
  expect(within(dialog).getByRole("img").getAttribute("src")).toBe("blob:/image");
  expect(within(dialog).getByRole("img").className).toContain("object-contain");
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).toBe(previousOverflow);
  expect(parent).not.toHaveBeenCalled();
});

it("закрывает просмотр кнопкой и фоном, но не кликом по изображению", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...idle, status: "ready", image_url: "/image" }))));
  render(<LocationArtwork campaignId="c" locationId="forest" name="Лес" />);
  const trigger = await screen.findByRole("button", { name: "Открыть иллюстрацию локации «Лес»" });
  fireEvent.click(trigger);
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("img"));
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Закрыть иллюстрацию" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(trigger);
  fireEvent.click(screen.getByTestId("location-artwork-backdrop"));
  expect(screen.queryByRole("dialog")).toBeNull();
});
