import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ManualPanel from "./ManualPanel";
import StagePanel from "./StagePanel";
import { mockApi } from "./testkit";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const props = { projectId: "ap_1", revision: 3, plot: { title: "Старое" }, busy: false, onChanged: vi.fn(), onPlotText: vi.fn(), onLore: vi.fn() };

it("задание для внешней модели показывает инструкцию и схему, без вызова модели", async () => {
  const mock = mockApi((c) =>
    c.url.endsWith("/tasks/lore")
      ? { body: { stage: "lore", system: "Ты автор мира", user: "Анкета: {}", schema: { properties: { overview: {} } }, how: "Вставьте ответ" } }
      : undefined,
  );
  render(<ManualPanel {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Задание для лора" }));
  const task = (await screen.findByLabelText("Задание: lore")) as HTMLTextAreaElement;
  expect(task.value).toContain("Ты автор мира");
  expect(task.value).toContain('"overview"');
  expect(mock.calls.every((c) => c.method === "GET")).toBe(true);
});

it("импорт лора берёт только разделы лора, а неудачный импорт каркаса показывает ошибки сервера", async () => {
  const onLore = vi.fn();
  mockApi((c) => (c.url.endsWith("/plot/import") ? { status: 409, body: { detail: "import_rejected", errors: ["нет поля title"] } } : undefined));
  render(<ManualPanel {...props} onLore={onLore} />);
  fireEvent.change(screen.getByLabelText("Импорт лора"), { target: { value: '```json\n{"overview": "Мир", "junk": 1}\n```' } });
  fireEvent.click(screen.getByRole("button", { name: "Импортировать лор" }));
  expect(onLore).toHaveBeenCalledWith({ overview: "Мир" });
  fireEvent.change(screen.getByLabelText("Импорт каркаса"), { target: { value: '{"locations": []}' } });
  fireEvent.click(screen.getByRole("button", { name: "Импортировать каркас" }));
  await waitFor(() => expect(screen.getByLabelText("Ошибки импорта").textContent).toContain("нет поля title"));
});

it("этап ждёт готовый предыдущий, а устаревший можно повторить или оставить", () => {
  const onPrepare = vi.fn();
  const onAccept = vi.fn();
  const view = {
    project_id: "ap_1",
    draft_revision: 3,
    stale: ["stage:geography"],
    stages: [
      { stage: "lore", status: "manual" },
      { stage: "plot", status: "ready" },
      { stage: "geography", status: "ready" },
      { stage: "materialize", status: "not_requested" },
      { stage: "maps", status: "not_requested" },
    ],
  };
  render(<StagePanel view={view} busy={false} onPrepare={onPrepare} onAcceptStale={onAccept} />);
  expect(screen.getByText("заполнено вручную")).toBeTruthy();
  const maps = screen.getByText("Карты").closest("li")!;
  expect((maps.querySelector("button") as HTMLButtonElement).disabled).toBe(true);
  expect(maps.textContent).toContain("сначала");
  const geo = screen.getByText("География").closest("li")!;
  expect(geo.getAttribute("data-state")).toBe("stale");
  fireEvent.click(screen.getByRole("button", { name: "Оставить как есть" }));
  expect(onAccept).toHaveBeenCalledWith("stage:geography");
  fireEvent.click(screen.getAllByRole("button", { name: "Повторить" })[0]);
  expect(onPrepare).toHaveBeenCalledWith("geography", true);
});
