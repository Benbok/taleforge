import { QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { mockApi, renderWithClient } from "../author/testkit";
import { authorKeys } from "../lib/authoring";
import NewGamePage from "./NewGamePage";

vi.mock("../components/Header", () => ({ default: () => null }));

const version = (id: string, n: number) => ({
  id,
  project_id: "ap_1",
  version: n,
  source_revision: 3,
  public_summary: { title: "Туманный остров", tagline: "Остров, где пропадают корабли" },
  published_at: "2026-10-18T10:00:00Z",
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(handler: Parameters<typeof mockApi>[0]) {
  const mock = mockApi(handler);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = renderWithClient(
    <Routes>
      <Route path="/" element={<NewGamePage />} />
      <Route path="/c/:id/manage" element={<p>Кабинет игры</p>} />
    </Routes>,
    client,
  );
  return { mock, ...view };
}

const library = (c: { url: string }) => (c.url === "/api/adventures" ? { body: [version("av_1", 1)] } : undefined);

it("пустая библиотека объясняет, что делать", async () => {
  mount((c) => (c.url === "/api/adventures" ? { body: [] } : undefined));
  expect(await screen.findByText(/пока нет опубликованных приключений/)).toBeTruthy();
});

it("запуск недоступен без выбора, двойной клик отправляет один запрос с одним ключом и ведёт в кабинет", async () => {
  const { mock } = mount((c) =>
    c.url === "/api/adventures/av_1/games" ? { status: 201, body: { campaign_id: "c_new", adventure_version_id: "av_1", url: "/c/c_new" } } : library(c),
  );
  const submit = (await screen.findByRole("button", { name: "Создать игру" })) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.click(await screen.findByRole("button", { name: /Туманный остров · версия 1/ }));
  fireEvent.change(screen.getByLabelText("Название игры"), { target: { value: "Вечер у костра" } });
  expect(submit.disabled).toBe(false);
  fireEvent.submit(submit.closest("form")!);
  fireEvent.submit(submit.closest("form")!);
  expect(await screen.findByText("Кабинет игры")).toBeTruthy();
  const launches = mock.calls.filter((c) => c.url === "/api/adventures/av_1/games");
  expect(launches).toHaveLength(1);
  expect(launches[0].body).toMatchObject({ options: { name: "Вечер у костра", players: 4, master: { type: "agent" } } });
  expect(typeof (launches[0].body as { request_key: string }).request_key).toBe("string");
});

it("новая версия в библиотеке не заменяет выбранную старую", async () => {
  const { mock, client } = mount((c) =>
    c.url.endsWith("/games") ? { status: 201, body: { campaign_id: "c_old", adventure_version_id: "av_1", url: "/c/c_old" } } : library(c),
  );
  fireEvent.click(await screen.findByRole("button", { name: /версия 1/ }));
  fireEvent.change(screen.getByLabelText("Название игры"), { target: { value: "Игра" } });
  client.setQueryData(authorKeys.library, [version("av_2", 2), version("av_1", 1)]);
  await screen.findByRole("button", { name: /версия 2/ });
  expect(screen.getByRole("button", { name: /версия 1/ }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.submit(screen.getByRole("button", { name: "Создать игру" }).closest("form")!);
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/games"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/games"))?.url).toBe("/api/adventures/av_1/games");
});
