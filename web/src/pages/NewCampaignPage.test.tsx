import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mockApi, renderWithClient, type Call } from "../author/testkit";
import { useSession } from "../stores/session";
import NewCampaignPage from "./NewCampaignPage";

vi.mock("../components/Header", () => ({ default: () => null }));

const options = {
  brief: { length: {}, pillars: {}, amounts: {}, emotions: {}, threat: {}, max_emotions: 2 },
  persona: { default: {} },
  presets: [{ id: "storyteller", name: "Сказитель", settings: {}, style: "" }],
};
const version = (id: string, n: number) => ({
  id,
  project_id: "ap_1",
  project_title: "тестова",
  version: n,
  source_revision: n,
  public_summary: { title: "Туманный остров", tagline: "Остров, где пропадают корабли", locations: 5 },
  published_at: `2026-10-1${n}T10:00:00Z`,
});
const book = { id: "am_1", title: "Затерянная шахта", summary: "Книга", levels: null, party_size: null, hooks: [], maps: 2 };

function handler(extra: (c: Call) => { status?: number; body: unknown } | undefined = () => undefined) {
  return (c: Call) => {
    const out = extra(c);
    if (out) return out;
    if (c.url === "/api/campaign-options") return { body: options };
    if (c.url === "/api/modules") return { body: [book] };
    if (c.url === "/api/adventures") return { body: [version("av_2", 2), version("av_1", 1)] };
    if (c.url.startsWith("/api/party-size")) return { body: { recommended: 4, min: 3, max: 6 } };
    if (["/api/packs", "/api/me/master-personas", "/api/me/master-presets", "/api/my-campaigns"].includes(c.url)) return { body: [] };
    return undefined;
  };
}

function mount(extra?: Parameters<typeof handler>[0]) {
  const mock = mockApi(handler(extra));
  renderWithClient(
    <Routes>
      <Route path="/" element={<NewCampaignPage />} />
      <Route path="/c/:id/manage" element={<p>Кабинет игры</p>} />
    </Routes>,
  );
  return mock;
}

async function chooseAuthored() {
  fireEvent.click(await screen.findByRole("radio", { name: "Готовое приключение" }));
  fireEvent.click(screen.getByRole("button", { name: "Готовое приключение" }));
  const list = screen.getByRole("listbox", { name: "Готовое приключение" });
  return list;
}

beforeEach(() => {
  localStorage.clear();
  useSession.setState({ user: { id: "u1", name: "Арти", platform_role: "admin", menu_music: {} as never } });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("приключения автора стоят в общем списке рядом с книгами, по одному на проект", async () => {
  mount();
  const list = await chooseAuthored();
  const items = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
  expect(items.filter((t) => t.includes("Туманный остров"))).toHaveLength(1);
  const authored = items.find((t) => t.includes("Туманный остров")) ?? "";
  expect(authored).toContain("АВТОР");
  expect(authored).toContain("проект «тестова» · версия 2");
  expect(items.some((t) => t.includes("Затерянная шахта") && t.includes("КНИГА"))).toBe(true);
});

it("приключение автора запускается из мастера с настройками стола и ведёт в кабинет", async () => {
  const mock = mount((c) =>
    c.url === "/api/adventures/av_2/games"
      ? { status: 201, body: { campaign_id: "c_new", adventure_version_id: "av_2", url: "/c/c_new" } }
      : undefined,
  );
  fireEvent.change(await screen.findByPlaceholderText(/Тени над Затонувшим/), { target: { value: "Вечер у костра" } });
  const list = await chooseAuthored();
  fireEvent.click(within(list).getByText("Туманный остров"));
  // Сложность задаёт автор: выбора нет, есть пояснение.
  expect(screen.queryByRole("radiogroup", { name: "Сложность" })).toBeNull();
  expect(screen.getByText(/Сложность вызовов задал автор/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /ДАЛЕЕ/ }));
  fireEvent.click(await screen.findByRole("radio", { name: "Автоматический допуск" }));
  fireEvent.click(screen.getByRole("button", { name: /ДАЛЕЕ/ }));
  expect(await screen.findByText(/берутся из приключения «Туманный остров»/)).toBeTruthy();
  fireEvent.change(screen.getByPlaceholderText(/пауки, пытки/), { target: { value: "пауки" } });
  fireEvent.click(screen.getByRole("button", { name: /ДАЛЕЕ/ }));
  expect(await screen.findByText(/вступление автора приключения/)).toBeTruthy();
  expect(screen.getByText("«Туманный остров», версия 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /СОЗДАТЬ КАМПАНИЮ/ }));
  expect(await screen.findByText("Кабинет игры")).toBeTruthy();
  const launches = mock.calls.filter((c) => c.url === "/api/adventures/av_2/games");
  expect(launches).toHaveLength(1);
  expect(launches[0].body).toMatchObject({
    options: {
      name: "Вечер у костра",
      players: 4,
      master: { type: "agent" },
      excluded_themes: ["пауки"],
      creation_rules: { review: "auto" },
      public_intro: null,
    },
  });
  expect(typeof (launches[0].body as { request_key: string }).request_key).toBe("string");
  expect(mock.calls.some((c) => c.url === "/api/campaigns" && c.method === "POST")).toBe(false);
});

it("книга по-прежнему создаёт кампанию обычным путём", async () => {
  const mock = mount((c) => (c.url === "/api/campaigns" && c.method === "POST" ? { status: 201, body: { id: "c_book" } } : undefined));
  fireEvent.change(await screen.findByPlaceholderText(/Тени над Затонувшим/), { target: { value: "Шахта" } });
  const list = await chooseAuthored();
  fireEvent.click(within(list).getByText("Затерянная шахта"));
  expect(screen.getByRole("radiogroup", { name: "Сложность" })).toBeTruthy();
  for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole("button", { name: /ДАЛЕЕ/ }));
  fireEvent.click(await screen.findByRole("button", { name: /СОЗДАТЬ КАМПАНИЮ/ }));
  await waitFor(() => expect(mock.calls.some((c) => c.url === "/api/campaigns" && c.method === "POST")).toBe(true));
  expect(mock.calls.find((c) => c.url === "/api/campaigns")?.body).toMatchObject({ module_id: "am_1", name: "Шахта" });
  expect(mock.calls.some((c) => c.url.endsWith("/games"))).toBe(false);
});
