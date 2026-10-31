import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { confirmAction } from "../stores/confirm";
import ActionButton from "./ActionButton";
import ConfirmDialog from "./ConfirmDialog";
import { answerConfirm } from "./confirmKit";

afterEach(cleanup);

const dialog = () => screen.queryByRole("dialog", { hidden: true });

it("запрос не уходит, пока действие не подтверждено; «Отмена» и Esc закрывают окно", async () => {
  const run = vi.fn(async () => {});
  render(<><ActionButton danger confirm={{ title: "Удалить кампанию «Туман»?", description: "Журнал будет удалён.", confirmLabel: "Удалить кампанию" }} run={run}>Удалить</ActionButton><ConfirmDialog /></>);
  fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
  expect(screen.getByRole("heading", { name: "Удалить кампанию «Туман»?", hidden: true })).toBeTruthy();
  expect(screen.getByText("Журнал будет удалён.")).toBeTruthy();
  expect(document.activeElement?.textContent).toBe("Отмена");
  answerConfirm("Отмена");
  expect(dialog()).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
  fireEvent(dialog()!, new Event("cancel", { cancelable: true }));
  expect(dialog()).toBeNull();
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
  answerConfirm("Удалить кампанию");
  await vi.waitFor(() => expect(run).toHaveBeenCalledTimes(1));
  await vi.waitFor(() => expect(dialog()).toBeNull());
});

it("во время запроса окно занято, а ошибка остаётся в нём с возможностью повторить", async () => {
  let fail = true;
  let release!: () => void;
  const run = vi.fn(() => new Promise<void>((resolve, reject) => { release = () => (fail ? reject(new Error("Сервер недоступен")) : resolve()); }));
  render(<><ActionButton confirm="Удалить файл? Он пропадёт из папки." run={run}>Убрать</ActionButton><ConfirmDialog /></>);
  fireEvent.click(screen.getByRole("button", { name: "Убрать" }));
  answerConfirm("Удалить");
  answerConfirm(/Удалить/); // повторный щелчок не запускает вторую операцию
  expect(run).toHaveBeenCalledTimes(1);
  fireEvent(dialog()!, new Event("cancel", { cancelable: true }));
  expect(dialog()).not.toBeNull(); // Esc во время запроса не закрывает окно
  await act(async () => release());
  expect((await screen.findByRole("alert", { hidden: true })).textContent).toBe("Сервер недоступен");
  fail = false;
  answerConfirm("Повторить");
  await act(async () => release());
  await vi.waitFor(() => expect(dialog()).toBeNull());
  expect(run).toHaveBeenCalledTimes(2);
});

it("второе окно не открывается поверх первого и не подтверждается само", async () => {
  render(<ConfirmDialog />);
  const first = confirmAction({ title: "Первое?" });
  const second = await confirmAction({ title: "Второе?" });
  expect(second).toBe(false);
  expect(screen.getByRole("heading", { name: "Первое?", hidden: true })).toBeTruthy();
  answerConfirm("Подтвердить");
  expect(await first).toBe(true);
});
