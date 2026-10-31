import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { mockApi, renderWithClient } from "../author/testkit";
import CampaignCoverStudio from "./CampaignCoverStudio";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const idle = { status: "idle", image_url: null, thumbnail_url: null, stale: false, enabled: true, can_generate: true, error: null };
const ready = { ...idle, status: "ready", image_url: "/api/campaigns/c1/cover/aw1", thumbnail_url: "/api/campaigns/c1/cover/aw1/thumbnail" };

function mount(handler: (call: { url: string; method: string; body: unknown }) => { status?: number; body: unknown } | undefined, unsaved = false) {
  const api = mockApi(handler);
  renderWithClient(<CampaignCoverStudio endpoint="/api/campaigns/c1/cover" name="Мир" unsaved={unsaved} />);
  return api;
}

it("создаёт обложку по кнопке и дальше предлагает пересоздание", async () => {
  let done = false;
  const { calls } = mount(({ method }) => ({ body: method === "POST" ? ((done = true), ready) : done ? ready : idle }));
  fireEvent.click(await screen.findByRole("button", { name: "Создать обложку" }));
  await screen.findByRole("button", { name: "Пересоздать обложку" });
  const posts = calls.filter((c) => c.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toMatchObject({ regenerate: false });
});

it("не даёт создавать обложку по несохранённым настройкам", async () => {
  const { calls } = mount(() => ({ body: idle }), true);
  const button = (await screen.findByRole("button", { name: "Создать обложку" })) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  expect(screen.getByText(/Сначала сохраните настройки стола/)).toBeTruthy();
  fireEvent.click(button);
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});

it("повторяет неопределённую ошибку с тем же ключом, а отказ сервера закрывает ключ", async () => {
  const outcomes = [{ status: 502, body: { detail: "шлюз" } }, { status: 502, body: { detail: "шлюз" } }, { status: 409, body: { detail: "нет" } }, { body: ready }];
  const { calls } = mount(({ method }) => (method === "POST" ? outcomes.shift() : { body: idle }));
  const click = async () => fireEvent.click(await screen.findByRole("button", { name: "Создать обложку" }));
  await click();
  await screen.findByRole("alert");
  await waitFor(() => expect((screen.getByRole("button", { name: "Создать обложку" }) as HTMLButtonElement).disabled).toBe(false));
  await click();
  await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
  await waitFor(() => expect((screen.getByRole("button", { name: "Создать обложку" }) as HTMLButtonElement).disabled).toBe(false));
  await click();
  await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(3));
  await waitFor(() => expect((screen.getByRole("button", { name: "Создать обложку" }) as HTMLButtonElement).disabled).toBe(false));
  await click();
  await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(4));
  const keys = calls.filter((c) => c.method === "POST").map((c) => (c.body as { request_key: string }).request_key);
  expect(keys[1]).toBe(keys[0]);
  expect(keys[2]).toBe(keys[0]);
  expect(keys[3]).not.toBe(keys[0]);
});

it("показывает прежнюю обложку при сбое замены", async () => {
  mount(({ method }) => (method === "POST" ? { status: 409, body: { detail: "Не удалось создать обложку." } } : { body: ready }));
  fireEvent.click(await screen.findByRole("button", { name: "Пересоздать обложку" }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/Прежняя обложка сохранена/);
});

it("ничего не показывает, если генерация не настроена и обложки нет", async () => {
  const { calls } = mount(() => ({ body: { ...idle, enabled: false, can_generate: false } }));
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  expect(screen.queryByText("Обложка мира")).toBeNull();
});

it("в студии мира рисует обложку мира, а унаследованная обложка предлагает свою", async () => {
  const inherited = { ...ready, inherited: true };
  const { calls } = mockApi(({ method }) => (method === "POST" ? { body: ready } : { body: inherited }));
  renderWithClient(<CampaignCoverStudio endpoint="/api/author/projects/p1/cover" name="Мир" unsaved={false} scope="world" />);
  expect(await screen.findByText(/получают все столы этого мира/)).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "Создать свою обложку" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ regenerate: false });
  expect(calls[0].url).toBe("/api/author/projects/p1/cover");
});
