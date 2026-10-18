import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AuthorWorkspace from "./AuthorWorkspace";
import { mockApi, renderWithClient } from "./testkit";

const stages = (overrides: Record<string, object> = {}) =>
  ["lore", "plot", "geography", "materialize", "maps", "validate"].map((stage) => ({
    stage,
    status: "not_requested",
    ...(overrides[stage] ?? {}),
  }));

const project = { id: "ap_1", title: "Туманный остров", draft_revision: 7, budget_usd: 2, brief: {} };
const content = {
  setting: { lore: { world: "Остров" } },
  plot: {
    regions: [{ id: "reg_hills", name: "Холмы" }],
    locations: [{ id: "loc_cave", name: "Пещера", region: "reg_hills" }],
    npcs: [{ id: "npc_a", name: "Лис" }],
    routes: [{ ref: "r1", from: "loc_cave/crawl", to: "loc_cave/main" }],
  },
};
const sketch = { shape: "room", cols: 6, rows: 4, party: [1, 1], walls: [], exits: [], features: [], terrain: [], edges: [] };

function api(extra: (c: { url: string; method: string; body: unknown }) => { status?: number; body: unknown } | undefined = () => undefined, st = stages()) {
  return mockApi((call) => {
    const out = extra(call);
    if (out) return out;
    if (call.url.startsWith("/api/author/projects/ap_1?view=summary"))
      return { body: { project, preparation: { project_id: "ap_1", draft_revision: 7, stages: st, spent_usd: 0.12, budget_usd: 2, cost_unknown: true, stale: [] } } };
    if (call.url.startsWith("/api/author/projects/ap_1?view=full"))
      return { body: { project, preparation: { project_id: "ap_1", draft_revision: 7, stages: st, spent_usd: 0, content } } };
    if (call.url.includes("/maps/loc_cave"))
      return { body: { location_ref: "loc_cave", name: "Пещера", areas: [{ area_ref: "main", name: "Вход", sketch, ports: { r1: { cells: [[1, 1]] } } }, { area_ref: "crawl", name: "Лаз", sketch, ports: {} }] } };
    return undefined;
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("показывает этапы running, blocked, stale и расходы с неизвестной стоимостью", async () => {
  const mock = mockApi((call) => {
    if (call.url.includes("view=summary"))
      return {
        body: {
          project,
          preparation: {
            project_id: "ap_1",
            draft_revision: 7,
            stages: stages({ lore: { status: "ready" }, plot: { status: "running" }, geography: { status: "blocked", error_code: "budget_exhausted" } }),
            spent_usd: 0.12,
            budget_usd: 2,
            cost_unknown: true,
            stale: ["layout:loc_cave"],
          },
        },
      };
    if (call.url.endsWith("/edits/accept-stale")) return { body: { applied: true, draft_revision: 8, affected: [], blocked_by: [] } };
    return undefined;
  });
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  expect(await screen.findByText("выполняется")).toBeTruthy();
  expect(screen.getByText("остановлено")).toBeTruthy();
  expect(screen.getByText("код: budget_exhausted")).toBeTruthy();
  expect(screen.getByText(/не считается нулём/)).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("layout:loc_cave");
  fireEvent.click(screen.getByRole("button", { name: "Принять как есть" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/accept-stale"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/accept-stale"))?.body).toMatchObject({ refs: ["layout:loc_cave"], expected_revision: 7 });
});

it("не грузит содержимое без явного раскрытия и не открывает сокет", async () => {
  const mock = api();
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  await screen.findByText("Туманный остров");
  expect(mock.calls.every((c) => !c.url.includes("view=full") && !c.url.includes("/maps/"))).toBe(true);
  expect(screen.queryByText("Пещера")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Показать содержимое/ }));
  await screen.findByText("Пещера");
  expect(mock.calls.some((c) => c.url.includes("view=full"))).toBe(true);
  expect(mock.socket).not.toHaveBeenCalled();
});

it("просмотр регион → локация → карта читает только GET и не создаёт героя", async () => {
  const mock = api();
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("button", { name: /Показать содержимое/ }));
  expect(await screen.findByText("Холмы")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Пещера" }));
  expect(await screen.findByRole("button", { name: "Лаз" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Лаз" }));
  fireEvent.click(screen.getByText(/Пещера · crawl|loc_cave\/crawl|Пещера · main/, { selector: "button" }));
  expect(screen.getByLabelText("Маршрут")).toBeTruthy();
  const mutating = mock.calls.filter((c) => c.method !== "GET" && !c.url.includes("/edits"));
  expect(mutating).toEqual([]);
  expect(mock.socket).not.toHaveBeenCalled();
});

it("ручная правка отправляет типизированную операцию с ревизией и показывает затронутое", async () => {
  const mock = api((call) =>
    call.url.endsWith("/edits")
      ? { body: { applied: true, draft_revision: 8, affected: [{ kind: "placement", ref: "loc_cave" }], blocked_by: [] } }
      : undefined,
  );
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("button", { name: /Показать содержимое/ }));
  const input = await screen.findByLabelText("Название: npc_a");
  fireEvent.change(input, { target: { value: "Рыжий лис" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Сохранить" })[1]);
  await screen.findByText(/Станут устаревшими: placement:loc_cave/);
  const sent = mock.calls.find((c) => c.url.endsWith("/edits"));
  expect(sent?.body).toMatchObject({
    patch: { operations: [{ op: "update_plot_object", ref: "npc_a", fields: { name: "Рыжий лис" } }] },
    expected_revision: 7,
  });
  expect(typeof (sent?.body as { request_key: string }).request_key).toBe("string");
});

it("повторная подготовка одного этапа отправляет stage и ключ", async () => {
  const mock = api((call) => (call.url.endsWith("/prepare") ? { status: 202, body: { job_id: "aj_1", stage: "lore", status: "queued", source_revision: 7 } } : undefined));
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  const buttons = await screen.findAllByRole("button", { name: "Подготовить" });
  fireEvent.click(buttons[0]);
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "lore", expected_revision: 7, regenerate: false });
});

it("отказ публикации показывает причины и не сообщает об успехе", async () => {
  api((call) => {
    if (call.url.includes("/validate")) return { body: { source_revision: 7, source_digest: "d", errors: [{ code: "missing_geometry", object_ref: "loc_cave/crawl" }], warnings: [], coverage: {} } };
    if (call.url.endsWith("/publish")) return { status: 409, body: { detail: "publication_blocked", issues: [{ code: "stale_result", object_ref: "layout:loc_cave", related_refs: [] }] } };
    return undefined;
  });
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Проверить" }));
  expect(await screen.findByText(/ошибок 1/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Опубликовать" }));
  expect(await screen.findByText(/Публикация отклонена: publication_blocked/)).toBeTruthy();
  expect(screen.getByText("stale_result")).toBeTruthy();
  expect(screen.queryByText(/Опубликована версия/)).toBeNull();
});

it("повтор неудачного этапа запускает новую попытку, а не возвращает старый результат", async () => {
  const mock = api(
    (call) => (call.url.endsWith("/prepare") ? { status: 202, body: { job_id: "aj_2", stage: "lore", status: "queued", source_revision: 7 } } : undefined),
    stages({ lore: { status: "failed", error_code: "llm_unavailable" } }),
  );
  renderWithClient(<AuthorWorkspace projectId="ap_1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/prepare"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/prepare"))?.body).toMatchObject({ stage: "lore", regenerate: true });
  expect(await screen.findByText("Этап поставлен в очередь.")).toBeTruthy();
});
