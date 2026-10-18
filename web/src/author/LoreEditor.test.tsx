import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import LoreEditor from "./LoreEditor";

afterEach(cleanup);

const lore = {
  overview: "Остров туманов, где рыбаки живут между приливами.",
  era_and_magic: "Позднее средневековье",
  history: [{ when: "век назад", event: "Пришёл туман" }],
  factions: [{ name: "Культ", goal: "разбудить спящего", relations: "враги рыбаков" }],
  figures: [{ name: "Ирса", role: "жрица", motive: "голос" }],
  regions: [{ id: "reg_coast", name: "Берег", description: "скалы" }],
  current_situation: "Пропадают корабли",
  mysteries: ["Кто поёт"],
  tone: "мрачный",
  taboos: [],
};

it("показывает все разделы и сохраняет изменённую фракцию целиком", () => {
  const onSave = vi.fn();
  render(<LoreEditor lore={lore} busy={false} onSave={onSave} />);
  for (const label of ["Обзор мира", "Эпоха и магия", "Хронология", "Фракции", "Ключевые фигуры", "Области", "Что происходит сейчас"]) {
    expect(screen.getAllByText(new RegExp(label)).length).toBeGreaterThan(0);
  }
  const save = screen.getByRole("button", { name: "Сохранить лор" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Цель 1"), { target: { value: "открыть врата" } });
  fireEvent.click(save);
  expect(onSave).toHaveBeenCalledWith({ factions: [{ name: "Культ", goal: "открыть врата", relations: "враги рыбаков" }] });
});

it("старый короткий лор подсказывает пересоздать его", () => {
  render(<LoreEditor lore={{ world: "Казематы" }} busy={false} onSave={() => undefined} />);
  expect(screen.getByText(/старого короткого формата/)).toBeTruthy();
  expect((screen.getByLabelText("Описание мира") as HTMLTextAreaElement).value).toBe("Казематы");
});
