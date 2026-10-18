import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AuthorWorkspace from "./AuthorWorkspace";
import { mockApi, renderWithClient } from "./testkit";

type Call = { url: string; method: string; body: unknown };
const stages = (overrides: Record<string, object> = {}) =>
  ["lore", "plot", "geography", "materialize", "maps", "validate"].map((stage) => ({ stage, status: "not_requested", ...(overrides[stage] ?? {}) }));

const project = { id: "ap_1", title: "Туманный остров", draft_revision: 7, budget_usd: 2, brief: {} };
const loreSchema = {
  type: "object",
  required: ["overview", "history"],
  properties: { overview: { type: "string" }, history: { type: "array", minItems: 4, items: { type: "object", required: ["when", "event"] } } },
};
const plotSchema = { type: "object", required: ["title", "locations"], properties: { title: { type: "string" }, locations: { type: "array", minItems: 2 } } };
const content = {
  setting: { lore: { overview: "Короткий обзор" } },
  plot: { regions: [{ id: "reg_hills", name: "Холмы" }], locations: [{ id: "loc_cave", name: "Пещера", region: "reg_hills" }], npcs: [{ id: "npc_a", name: "Лис" }] },
};

function api(extra: (c: Call) => { status?: number; body: unknown } | undefined = () => undefined, st = stages(), stale: string[] = []) {
  return mockApi((call) => {
    const out = extra(call);
    if (out) return out;
    const prep = { project_id: "ap_1", draft_revision: 7, stages: st, spent_usd: 0.0038, budget_usd: 2, cost_unknown: false, stale };
    if (call.url.endsWith("?view=summary")) return { body: { project, preparation: prep } };
    if (call.url.endsWith("?view=full")) return { body: { project, preparation: { ...prep, content } } };
    if (call.url.endsWith("/tasks/lore")) return { body: { stage: "lore", system: "Ты автор мира", user: "Анкета", schema: loreSchema, how: "Вставьте ответ" } };
    if (call.url.endsWith("/tasks/plot")) return { body: { stage: "plot", system: "Ты архитектор", user: "Анкета", schema: plotSchema, how: "Вставьте ответ" } };
    if (call.url.includes("/maps/loc_cave")) return { body: { location_ref: "loc_cave", name: "Пещера", areas: [] } };
    return undefined;
  });
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const open = async () => fireEvent.click((await screen.findAllByRole("button", { name: "Показать содержимое" }))[0]);
const nav = () => screen.getByRole("navigation", { name: "Шаги подготовки" });

it("по умолчанию скрывает содержимое и не запрашивает его, пока автор не откроет", async () => {
  const mock = api();
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await screen.findByText("Туманный остров");
  expect(mock.calls.some((c) => c.url.includes("view=full"))).toBe(false);
  expect(screen.getByText(/Содержимое скрыто/)).toBeTruthy();
  await open();
  await screen.findByText("Что заполнено в лоре");
  expect(mock.calls.some((c) => c.url.includes("view=full"))).toBe(true);
  expect(localStorage.getItem("author:reveal:ap_1")).toBe("1");
  expect(mock.socket).not.toHaveBeenCalled();
});

it("шаги показывают порядок: следующие закрыты, пока не готов предыдущий", async () => {
  api(undefined, stages({ lore: { status: "ready" } }));
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await screen.findByText("Туманный остров");
  const state = (title: string) => within(nav()).getByText(title).closest("button")!.getAttribute("data-state");
  expect(state("Лор мира")).toBe("done");
  expect(state("Места, NPC и предметы")).toBe("locked");
  fireEvent.click(within(nav()).getByText("Карты"));
  // закрытый шаг не показывает данные каркаса, а ведёт к шагу, которого не хватает
  fireEvent.click(await screen.findByRole("button", { name: "Перейти к шагу «Места, NPC и предметы»" }));
  expect(await screen.findByRole("button", { name: "Перейти к шагу «География»" })).toBeTruthy();
});

it("вставка лора показывает, что станет заполненным и что расходится со схемой, и сохраняет только разделы лора", async () => {
  const mock = api((c) => (c.url.endsWith("/edits") ? { body: { applied: true, draft_revision: 8, affected: [], blocked_by: [] } } : undefined));
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await open();
  const box = await screen.findByRole("textbox", { name: "Вставить лор (JSON)" });
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/tasks/lore"))).toBe(true));
  const pasted = { overview: "Мир. ".repeat(60), history: [{ when: "давно" }], junk: 1 };
  fireEvent.change(box, { target: { value: "Вот ответ:\n```json\n" + JSON.stringify(pasted) + "\n```" } });
  const after = await screen.findByRole("region", { name: "После вставки" });
  expect(within(after).getByText("Обзор мира").closest("button")!.getAttribute("data-ok")).toBe("true");
  expect(within(after).getByText("Хронология").closest("button")!.getAttribute("data-ok")).toBe("false");
  await waitFor(() => expect(screen.getByLabelText("Расхождения со схемой").textContent).toContain("history[0].event"));
  expect(screen.getByLabelText("Расхождения со схемой").textContent).toContain("нужно не меньше 4");
  fireEvent.click(screen.getByRole("button", { name: "Добавить в лор" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/edits"))).toBe(true));
  const sent = mock.calls.find((c) => c.url.endsWith("/edits"))!.body as { patch: { operations: { fields: Record<string, unknown> }[] } };
  expect(Object.keys(sent.patch.operations[0].fields).sort()).toEqual(["history", "overview"]);
});

it("каркас сюжета, отклонённый сервером, показывает его ошибки и не сообщает об успехе", async () => {
  api((c) => (c.url.endsWith("/plot/import") ? { status: 409, body: { detail: "import_rejected", errors: ["NPC npc_x: нет шаблона"] } } : undefined));
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await open();
  fireEvent.click(within(nav()).getByText("Сюжет и NPC"));
  const box = await screen.findByRole("textbox", { name: "Вставить каркас сюжета (JSON)" });
  fireEvent.change(box, { target: { value: '{"title": "Т", "locations": [{}, {}]}' } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить и принять каркас" }));
  expect(await screen.findByLabelText("Ошибки сервера")).toBeTruthy();
  expect(screen.getByText("NPC npc_x: нет шаблона")).toBeTruthy();
  expect(screen.queryByText(/Каркас принят/)).toBeNull();
});

it("устаревший шаг можно повторить или оставить, генерация помечена платной", async () => {
  const mock = api(
    (c) =>
      c.url.endsWith("/prepare")
        ? { status: 202, body: { job_id: "aj_2", stage: "geography", status: "queued", source_revision: 7 } }
        : c.url.endsWith("/accept-stale")
          ? { body: { applied: true, draft_revision: 8, affected: [], blocked_by: [] } }
          : undefined,
    stages({ lore: { status: "ready" }, plot: { status: "ready" }, geography: { status: "ready" } }),
    ["stage:geography"],
  );
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  expect(await screen.findByRole("button", { name: "Новый вариант (платно)" })).toBeTruthy();
  fireEvent.click(within(nav()).getByText("География"));
  fireEvent.click(await screen.findByRole("button", { name: "Повторить" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "geography", regenerate: true, expected_revision: 7 });
  fireEvent.click(screen.getByRole("button", { name: "Оставить как есть" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/accept-stale"))).toBe(true));
});

it("отказ публикации показывает причины", async () => {
  api((c) => {
    if (c.url.includes("/validate")) return { body: { source_revision: 7, source_digest: "d", errors: [{ code: "missing_geometry", object_ref: "loc_cave/crawl" }], warnings: [], coverage: {} } };
    if (c.url.endsWith("/publish")) return { status: 409, body: { detail: "publication_blocked", issues: [{ code: "stale_result", object_ref: "layout:loc_cave", related_refs: [] }] } };
    return undefined;
  });
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await screen.findByText("Туманный остров");
  fireEvent.click(within(nav()).getByText("Проверка и публикация"));
  fireEvent.click(await screen.findByRole("button", { name: "Проверить" }));
  expect(await screen.findByText(/ошибок 1/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Опубликовать" }));
  expect(await screen.findByText(/Публикация отклонена/)).toBeTruthy();
  expect(screen.getByText("stale_result")).toBeTruthy();
});


it("принятый каркас сразу запускает бесплатную проверку географии", async () => {
  const mock = api((c) =>
    c.url.endsWith("/plot/import")
      ? { body: { plan_version_id: "pl_1", cleared_entities: 0, source: "import" } }
      : c.url.endsWith("/prepare")
        ? { status: 202, body: { job_id: "aj_g", stage: "geography", status: "queued", source_revision: 8 } }
        : undefined,
  );
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await open();
  fireEvent.click(within(nav()).getByText("Сюжет и NPC"));
  fireEvent.change(await screen.findByRole("textbox", { name: "Вставить каркас сюжета (JSON)" }), { target: { value: '{"title": "Т", "locations": [{}, {}]}' } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить и принять каркас" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "geography" });
});

it("на шаге «Карты» видны карты всех мест и откуда взялась планировка", async () => {
  const sketch = { shape: "room", cols: 6, rows: 4, party: [1, 1], walls: [], exits: [], features: [], terrain: [], edges: [] };
  const mock = api(
    (c) =>
      c.url.includes("/maps/loc_cave")
        ? { body: { location_ref: "loc_cave", name: "Пещера", layout_quality: "fallback", areas: [{ area_ref: "main", name: "Вход", sketch, ports: {} }] } }
        : undefined,
    stages({ lore: { status: "ready" }, plot: { status: "ready" }, geography: { status: "ready" }, materialize: { status: "ready" } }),
  );
  localStorage.setItem("author:reveal:ap_1", "1");
  localStorage.setItem("author:step:ap_1", "maps");
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("tab", { name: "Карты мест" }));
  expect(await screen.findByText("запасная планировка по шаблону: модель не ответила")).toBeTruthy();
  expect(screen.getByRole("group", { name: "Места" })).toBeTruthy();
  expect(mock.calls.every((c) => c.method === "GET")).toBe(true);
});

it("кнопка «Пересобрать карты» запускает пересборку всех мест", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const mock = api(
    (c) => (c.url.endsWith("/prepare") ? { status: 202, body: { job_id: "aj_m", stage: "maps", status: "queued", source_revision: 7 } } : undefined),
    stages({ lore: { status: "ready" }, plot: { status: "ready" }, geography: { status: "ready" }, materialize: { status: "ready" } }),
  );
  localStorage.setItem("author:step:ap_1", "maps");
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Пересобрать карты" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "maps", target_ref: "*", regenerate: true });
});

it("«Пересобрать эту карту» пересобирает только показанное место", async () => {
  const sketch = { shape: "room", cols: 6, rows: 4, party: [1, 1], walls: [], exits: [], features: [], terrain: [], edges: [] };
  const mock = api(
    (c) =>
      c.url.includes("/maps/loc_cave")
        ? { body: { location_ref: "loc_cave", name: "Пещера", layout_quality: "fallback", areas: [{ area_ref: "main", name: "Вход", sketch, ports: {} }] } }
        : c.url.endsWith("/prepare")
          ? { status: 202, body: { job_id: "aj_one", stage: "maps", status: "queued", source_revision: 7 } }
          : undefined,
    stages({ lore: { status: "ready" }, plot: { status: "ready" }, geography: { status: "ready" }, materialize: { status: "ready" } }),
  );
  localStorage.setItem("author:reveal:ap_1", "1");
  localStorage.setItem("author:step:ap_1", "maps");
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("tab", { name: "Карты мест" }));
  fireEvent.click(await screen.findByRole("button", { name: "Пересобрать эту карту" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "maps", target_ref: "loc_cave", regenerate: true });
});

it("характер персонажа сохраняется правкой его полей", async () => {
  const mock = api((c) => (c.url.endsWith("/edits") ? { body: { applied: true, draft_revision: 8, affected: [], blocked_by: [] } } : undefined));
  localStorage.setItem("author:reveal:ap_1", "1");
  localStorage.setItem("author:step:ap_1", "plot");
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  const field = await screen.findByLabelText("Характер (2–3 черты): Лис");
  fireEvent.change(field, { target: { value: "хитёр, труслив" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить характер" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/edits"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/edits"))?.body).toMatchObject({
    patch: { operations: [{ op: "update_plot_object", ref: "npc_a", fields: { character: "хитёр, труслив" } }] },
  });
  expect(screen.getAllByText("Характеры персонажей").length).toBe(2); // чек-лист и раздел редактора
});
