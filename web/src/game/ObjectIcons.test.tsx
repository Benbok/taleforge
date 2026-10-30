import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ObjectIconControls, useObjectIcons } from "./ObjectIcons";
import { LocationMapSvg } from "./LocationMap";
import type { MapLocationPlan } from "./map";

vi.mock("../lib/authedImage", () => ({ useAuthedImage: (url: string) => `blob:${url}` }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const item = (id: string, name: string, over: object = {}) => ({
  id, name, status: "idle", image_url: null as string | null, stale: false, enabled: true, can_generate: true, error: null, ...over,
});
const reply = (body: object, status = 200) => new Response(JSON.stringify(body), { status });

function Harness() {
  const icons = useObjectIcons("c", "yard");
  return <><ObjectIconControls icons={icons} /><output data-testid="urls">{JSON.stringify(icons.urls)}</output></>;
}

it("кнопка показывает, сколько значков не хватает, и ничего не запускает сама", async () => {
  const methods: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    methods.push(init?.method ?? "GET");
    return reply({ enabled: true, can_generate: true, objects: [item("a", "Камень"), item("b", "Дуб"), item("c", "Шапка", { status: "ready", image_url: "/i/c" })] });
  }));
  render(<Harness />);
  expect(await screen.findByRole("button", { name: "Нарисовать значки предметов (2)" })).toBeTruthy();
  expect(methods.every((m) => m === "GET")).toBe(true);
  expect(JSON.parse(screen.getByTestId("urls").textContent!)).toEqual({ c: "/i/c" });
});

it("клик рисует недостающие значки по очереди, каждый со своим ключом, и они появляются", async () => {
  const posts: { url: string; key: string }[] = [];
  const ready: Record<string, string> = {};
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const id = url.match(/objects\/([^/]+)\/icon/)![1];
      posts.push({ url, key: JSON.parse(String(init.body)).request_key });
      ready[id] = `/i/${id}`;
      return reply(item(id, id, { status: "ready", image_url: ready[id] }));
    }
    return reply({ enabled: true, can_generate: true, objects: [item("a", "Камень", ready.a ? { status: "ready", image_url: ready.a } : {}), item("b", "Дуб", ready.b ? { status: "ready", image_url: ready.b } : {})] });
  }));
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Нарисовать значки предметов (2)" }));
  await waitFor(() => expect(JSON.parse(screen.getByTestId("urls").textContent!)).toEqual({ a: "/i/a", b: "/i/b" }));
  expect(posts.map((p) => p.url.match(/objects\/([^/]+)\//)![1])).toEqual(["a", "b"]);
  expect(new Set(posts.map((p) => p.key)).size).toBe(2);
  expect(screen.queryByRole("button", { name: /Нарисовать значки/ })).toBeNull();
});

it("сбой одного значка не останавливает остальные и показывает ошибку", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      return url.includes("/a/") ? reply({ detail: "ComfyUI недоступен" }, 409) : reply(item("b", "Дуб", { status: "ready", image_url: "/i/b" }));
    }
    return reply({ enabled: true, can_generate: true, objects: [item("a", "Камень"), item("b", "Дуб")] });
  }));
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Нарисовать значки предметов (2)" }));
  await waitFor(() => expect(JSON.parse(screen.getByTestId("urls").textContent!)).toEqual({ b: "/i/b" }));
  expect(screen.getByRole("alert").textContent).toMatch(/Камень/);
});

it("игроку без права, при выключенной функции и когда всё нарисовано кнопки нет", async () => {
  for (const body of [
    { enabled: true, can_generate: false, objects: [item("a", "Камень", { can_generate: false })] },
    { enabled: false, can_generate: false, objects: [item("a", "Камень", { enabled: false, can_generate: false })] },
    { enabled: true, can_generate: true, objects: [item("a", "Камень", { status: "ready", image_url: "/i/a" })] },
  ]) {
    vi.stubGlobal("fetch", vi.fn(async () => reply(body)));
    const view = render(<Harness />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await waitFor(() => expect(view.getByTestId("urls")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Нарисовать значки/ })).toBeNull();
    cleanup();
  }
});

const sketch = { shape: "open" as const, cols: 4, rows: 3, party: [0, 0] as [number, number], walls: [], exits: [],
  features: [
    { id: "f1", entity_id: "a", name: "Камень", kind: "object" as const, cells: [[1, 1, 1, 1]] },
    { id: "f2", entity_id: "b", name: "Дуб", kind: "object" as const, cells: [[2, 1, 2, 1]] },
  ] };
const plan: MapLocationPlan = { root_id: "r", here_id: "here", areas: [{ id: "here", name: "Здесь", offset: [0, 0], level: 0, status: "here", revision: 1, sketch }] };

it("на карте предмет с нарисованным значком показывает картинку, остальные — значок по названию", () => {
  const { container } = render(<LocationMapSvg map={plan} idPrefix="o" backdrop={{ areaId: "here", url: "/img/1" }} objectIcons={{ a: "/i/a" }} />);
  const markers = [...container.querySelectorAll("[data-feature-marker]")];
  expect(markers).toHaveLength(2);
  const hrefs = markers.map((m) => m.querySelector("image")?.getAttribute("href") ?? null);
  expect(hrefs).toEqual(["blob:/i/a", null]);
  expect(markers[1].querySelector("svg")).not.toBeNull();
});
