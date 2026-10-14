import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { BuilderOptions, CampaignHero, LibraryHero } from "../lib/builder";
import CampaignHeroPage from "./CampaignHeroPage";
import LibraryHeroPage from "./LibraryHeroPage";

const opts: BuilderOptions = {
  ability_methods: ["standard_array", "roll"],
  standard_array: [15, 14, 13, 12, 10, 8],
  point_buy: { budget: 27, cost: {} },
  start_level: 1,
  classes: [{
    id: "class.fighter", name: "Воин", description: "", hit_die: 10,
    saving_throws: ["str", "con"], skills_choose: { count: 2, from: ["athletics", "perception"] },
    equipment_fixed: [], equipment_choices: [[[ { item: "item.longsword", name: "Меч" } ]]],
  }],
  origins: [{
    id: "origin.human", name: "Человек", description: "", ability_bonuses: {},
    ability_groups: [], speed: 30, features: [],
  }],
  weapons: {},
};

const library: LibraryHero = {
  id: "lib1", name: "Бран", class_name: "Воин", origin_name: "Эльф",
  pack_id: null, world_name: "Базовые правила", level: 1, errors: [],
  sheet: {
    class_id: "class.fighter", origin_id: "origin.elf", ability_method: "standard_array",
    abilities: { str: 15, dex: 13, con: 14, int: 8, wis: 12, cha: 10 },
    skills: ["athletics", "perception"], equipment_choices: [{ choice: 0, option: 0, items: [] }],
  },
  public_bio: "Наёмник со шрамом", private_backstory: "Бежал из гарнизона",
};

const clients: QueryClient[] = [];
function open(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(qc);
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/c/:id/hero" element={<CampaignHeroPage />} />
          <Route path="/heroes/:hid" element={<LibraryHeroPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((qc) => qc.clear());
  vi.unstubAllGlobals();
});

it("opens an incompatible library copy with its saved data and submits the same hero after adaptation", async () => {
  let copy: CampaignHero | null = null;
  let detailReads = 0;
  let resolveDetail!: (r: Response) => void;
  const detail = new Promise<Response>((resolve) => { resolveDetail = resolve; });
  const writes: { path: string; method: string; body: Record<string, unknown> }[] = [];
  const fetcher = vi.fn(async (path: string, init: RequestInit) => {
    const method = init.method;
    if (path === "/api/campaigns/c1")
      return response({ id: "c1", name: "Тест", my_seat_id: "s1", my_role: "player", pack_id: "world" });
    if (path === "/api/campaigns/c1/character-options") return response(opts);
    if (path === "/api/me/characters") return response([library]);
    if (path === "/api/campaigns/c1/character-preview") return response({ errors: [], derived: null, inventory: [] });
    if (path === "/api/campaigns/c1/characters" && method === "GET") return response(copy ? [copy] : []);
    if (path === "/api/campaigns/c1/characters/from-library/lib1") {
      const { origin_id: _origin, ...sheet } = library.sheet!;
      copy = { ...library, id: "copy1", seat_id: "s1", status: "draft", sheet,
        errors: ["Выберите происхождение этого мира"] };
      return response(copy, 201);
    }
    if (path === "/api/campaigns/c1/characters/copy1" && method === "GET")
      return detailReads++ === 0 ? detail : response(copy);
    if (path === "/api/campaigns/c1/characters/copy1" && method === "PUT") {
      const body = JSON.parse(String(init.body));
      writes.push({ path, method, body });
      copy = { ...copy!, name: body.name, sheet: { ...copy!.sheet, ...body }, errors: [] };
      return response(copy);
    }
    if (path === "/api/campaigns/c1/characters" && method === "POST")
      return response({ detail: "у этого места уже есть персонаж" }, 409);
    if (path === "/api/campaigns/c1/characters/copy1/submit") {
      copy = { ...copy!, status: "submitted" };
      return response({ status: "submitted", errors: [] });
    }
    throw new Error(`Unexpected request: ${method} ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  open("/c/c1/hero");
  fireEvent.click(await screen.findByRole("button", { name: "ВЗЯТЬ КОПИЮ В КАМПАНИЮ" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([path]) => path === "/api/campaigns/c1/characters/copy1")).toBe(true));
  expect((screen.getByPlaceholderText("Введите имя или прозвище персонажа") as HTMLInputElement).value).toBe("Бран");
  await act(async () => { resolveDetail(response(copy)); });

  await waitFor(() => expect((screen.getByPlaceholderText("Введите имя или прозвище персонажа") as HTMLInputElement).value).toBe("Бран"));
  fireEvent.click(screen.getByRole("button", { name: "Показать всё разом" }));
  expect((screen.getByPlaceholderText(/Как выглядит герой/) as HTMLTextAreaElement).value).toBe("Наёмник со шрамом");
  expect((screen.getByPlaceholderText(/Скрытые мотивы/) as HTMLTextAreaElement).value).toBe("Бежал из гарнизона");
  fireEvent.click(screen.getByRole("radio", { name: /Человек/ }));
  fireEvent.click(screen.getAllByRole("button", { name: "ОТПРАВИТЬ МАСТЕРУ НА ПРОВЕРКУ →" }).at(-1)!);
  expect(await screen.findByText(/Ожидает проверки мастером стола/)).toBeTruthy();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({
    method: "PUT", path: "/api/campaigns/c1/characters/copy1",
    body: { name: "Бран", class_id: "class.fighter", origin_id: "origin.human",
      abilities: { str: 15, dex: 13, con: 14, int: 8, wis: 12, cha: 10 },
      skills: ["athletics", "perception"], equipment_choices: [{ choice: 0, option: 0, items: [] }],
      public_bio: "Наёмник со шрамом", private_backstory: "Бежал из гарнизона" },
  });
});

it("creates a library hero outside a campaign, updates it after navigation and restores it on reopening", async () => {
  let stored: LibraryHero | null = null;
  const methods: string[] = [];
  vi.stubGlobal("fetch", async (path: string, init: RequestInit) => {
    if (path === "/api/me/worlds") return response([{ id: null, name: "Базовые правила" }]);
    if (path === "/api/me/character-options") return response(opts);
    if (path === "/api/me/character-preview") return response({ errors: [], derived: null, inventory: [] });
    if (path === "/api/me/characters/lib1" && init.method === "GET") return response(stored);
    if ((path === "/api/me/characters" && init.method === "POST") ||
        (path === "/api/me/characters/lib1" && init.method === "PUT")) {
      const body = JSON.parse(String(init.body));
      methods.push(init.method);
      stored = { ...library, name: body.name, sheet: body };
      return response(stored, init.method === "POST" ? 201 : 200);
    }
    throw new Error(`Unexpected request: ${init.method} ${path}`);
  });
  const page = open("/heroes/new");
  const input = await screen.findByPlaceholderText("Введите имя или прозвище персонажа");
  fireEvent.change(input, { target: { value: "Бран" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить в библиотеку" }));
  await screen.findByRole("heading", { name: "Бран", level: 1 });
  fireEvent.change(screen.getByPlaceholderText("Введите имя или прозвище персонажа"), { target: { value: "Бран Седой" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить в библиотеку" }));
  await screen.findByRole("heading", { name: "Бран Седой", level: 1 });
  expect(methods).toEqual(["POST", "PUT"]);
  page.unmount();
  open("/heroes/lib1");
  expect((await screen.findByPlaceholderText("Введите имя или прозвище персонажа") as HTMLInputElement).value).toBe("Бран Седой");
});

it("submits a ready library copy directly without opening an empty builder", async () => {
  let copy: CampaignHero | null = null;
  const submitted: string[] = [];
  vi.stubGlobal("fetch", async (path: string, init: RequestInit) => {
    if (path === "/api/campaigns/c1")
      return response({ id: "c1", name: "Тест", my_seat_id: "s1", my_role: "player", pack_id: null });
    if (path === "/api/campaigns/c1/character-options") return response(opts);
    if (path === "/api/me/characters") return response([library]);
    if (path === "/api/campaigns/c1/characters" && init.method === "GET") return response(copy ? [copy] : []);
    if (path === "/api/campaigns/c1/characters/from-library/lib1") {
      copy = { ...library, id: "copy1", seat_id: "s1", status: "draft", errors: [] };
      return response(copy, 201);
    }
    if (path === "/api/campaigns/c1/characters/copy1/submit") {
      submitted.push(path);
      copy = { ...copy!, status: "submitted" };
      return response({ status: "submitted", errors: [] });
    }
    if (path === "/api/campaigns/c1/characters/copy1" && init.method === "GET") return response(copy);
    throw new Error(`Unexpected request: ${init.method} ${path}`);
  });
  open("/c/c1/hero");
  fireEvent.click(await screen.findByRole("button", { name: "ВЗЯТЬ КОПИЮ В КАМПАНИЮ" }));
  expect(await screen.findByText(/Ожидает проверки мастером стола/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Бран", level: 2 })).toBeTruthy();
  expect(screen.queryByPlaceholderText("Введите имя или прозвище персонажа")).toBeNull();
  expect(submitted).toEqual(["/api/campaigns/c1/characters/copy1/submit"]);
});
