import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BackdropControls, useMapBackdrop } from "./MapBackdrop";
import { LocationMapSvg } from "./LocationMap";
import type { MapLocationPlan } from "./map";

vi.mock("../lib/authedImage", () => ({ useAuthedImage: (url: string) => `blob:${url}` }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

const idle = { status: "idle", image_url: null as string | null, stale: false, enabled: true, can_generate: true, error: null as string | null };
const reply = (body: object) => new Response(JSON.stringify(body));

function Harness({ locationId = "yard" }: { locationId?: string }) {
  const backdrop = useMapBackdrop("c", locationId);
  return <BackdropControls backdrop={backdrop} />;
}

it("кнопка видна только когда можно создавать, просмотр ничего не запускает", async () => {
  const methods: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => { methods.push(init?.method ?? "GET"); return reply({ ...idle, can_generate: false }); }));
  render(<Harness />);
  await waitFor(() => expect(methods.length).toBeGreaterThan(0));
  expect(screen.queryByRole("button", { name: /подложку/i })).toBeNull();
  expect(methods.every((m) => m === "GET")).toBe(true);
});

it("клик отправляет запрос с ключом и показывает «Пересоздать» после готовности", async () => {
  const bodies: { request_key: string; regenerate: boolean }[] = [];
  let state = idle;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") { bodies.push(JSON.parse(String(init.body))); state = { ...idle, status: "ready", image_url: "/img/1" }; }
    return reply(state);
  }));
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Создать подложку" }));
  expect(await screen.findByRole("button", { name: /Пересоздать подложку/ })).toBeTruthy();
  expect(bodies).toHaveLength(1);
  expect(bodies[0].request_key.length).toBeGreaterThan(8);
  expect(bodies[0].regenerate).toBe(false);
});

it("устаревшая подложка предлагает обновление с regenerate=true", async () => {
  const bodies: { regenerate: boolean }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") bodies.push(JSON.parse(String(init.body)));
    return reply({ ...idle, status: "ready", image_url: "/img/1", stale: true });
  }));
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: /Обновить подложку/ }));
  await waitFor(() => expect(bodies).toEqual([{ request_key: expect.any(String), regenerate: true }]));
  expect(screen.getByText(/Подложка устарела/)).toBeTruthy();
});

it("при ожидании опрашивает статус и подхватывает готовую картинку", async () => {
  vi.useFakeTimers();
  let state = { ...idle, status: "pending" };
  vi.stubGlobal("fetch", vi.fn(async () => reply(state)));
  await act(async () => { render(<Harness />); });
  expect(screen.getByRole("status").textContent).toMatch(/Рисую подложку/);
  state = { ...idle, status: "ready", image_url: "/img/2" };
  await act(async () => { await vi.advanceTimersByTimeAsync(2600); });
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByRole("button", { name: /Пересоздать подложку/ })).toBeTruthy();
});

it("выключенная функция ничего не рисует", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => reply({ ...idle, enabled: false, can_generate: false })));
  const { container } = render(<Harness />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(container.textContent).toBe("");
});

it("поздний ответ предыдущей области не подменяет новую", async () => {
  let resolveOld: (value: Response) => void = () => undefined;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/yard/")) return new Promise<Response>((resolve) => { resolveOld = resolve; });
    return reply({ ...idle, status: "ready", image_url: "/img/new" });
  }));
  const page = render(<Harness key="yard" locationId="yard" />);
  page.rerender(<Harness key="hall" locationId="hall" />);
  expect(await screen.findByRole("button", { name: /Пересоздать подложку/ })).toBeTruthy();
  await act(async () => { resolveOld(reply({ ...idle })); });
  expect(screen.queryByRole("button", { name: "Создать подложку" })).toBeNull();
});

const sketch = { shape: "open" as const, cols: 4, rows: 3, party: [0, 0] as [number, number], walls: [], exits: [], features: [] };
const plan: MapLocationPlan = {
  root_id: "r", here_id: "here", areas: [
    { id: "here", name: "Здесь", offset: [0, 0], level: 0, status: "here", revision: 1, sketch },
    { id: "old", name: "Раньше", offset: [5, 0], level: 0, status: "remembered", revision: 1, sketch },
  ],
};

it("картина лежит под текущей областью, на всю сетку, и не перехватывает клики", () => {
  const { container } = render(<LocationMapSvg map={plan} idPrefix="t" backdrop={{ areaId: "here", url: "/img/1" }} />);
  const images = container.querySelectorAll("[data-map-backdrop]");
  expect(images).toHaveLength(1);
  const image = images[0];
  expect(image.closest("[data-area-id]")?.getAttribute("data-area-id")).toBe("here");
  expect(image.getAttribute("href")).toBe("blob:/img/1");
  expect([image.getAttribute("width"), image.getAttribute("height")]).toEqual(["4", "3"]);
  expect(image.getAttribute("preserveAspectRatio")).toBe("none");
  expect(image.getAttribute("pointer-events")).toBe("none");
  const surface = image.closest("[data-area-id]")!.querySelector("[data-sketch-surface]")!;
  expect(image.compareDocumentPosition(surface) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("без картины слой не рисуется", () => {
  const { container } = render(<LocationMapSvg map={plan} idPrefix="t" />);
  expect(container.querySelector("[data-map-backdrop]")).toBeNull();
});
