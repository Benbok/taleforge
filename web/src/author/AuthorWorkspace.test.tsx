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
  expect(await screen.findByText("Сначала завершите предыдущий шаг.")).toBeTruthy();
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
