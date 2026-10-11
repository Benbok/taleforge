import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useGame } from "../stores/game";
import type { HeroSheet } from "../lib/types";
import HeroHud from "./HeroHud";
import HeroWindow, { useHeroWindow } from "./HeroWindow";
import EntityPopover from "./EntityPopover";
import RichText from "./RichText";
import { useInspector } from "./inspector";

afterEach(() => {
  cleanup();
  useInspector.getState().close();
  useHeroWindow.getState().hide();
  useGame.getState().reset();
});

function setup() {
  const sheet = {
    id: "ch_bran", name: "Бран", level: 1, inventory: [],
    resources: { hp: 10, hp_max: 10 },
    derived: { effects: [{ id: "ef_instance", template: "condition.frightened", name: "Испуганный", stacks: 1 }] },
  } as unknown as HeroSheet;
  useGame.setState({ sheet, cards: {
    "condition.frightened": {
      id: "condition.frightened", name: "Испуганный", type: "effect",
      description: "Пока источник страха в поле зрения, проверки и атаки с помехой.",
    },
  } });
}

it("статус в панели героя открывает описание вместо листа героя", () => {
  setup();
  render(<><HeroHud /><EntityPopover /></>);
  fireEvent.click(screen.getByRole("button", { name: "Испуганный" }));
  expect(screen.getByRole("dialog", { name: "Карточка: Испуганный" })).toBeTruthy();
  expect(screen.getByText(/проверки и атаки с помехой/)).toBeTruthy();
  expect(useHeroWindow.getState().open).toBe(false);
});

it("статус в листе и ссылка в тексте открывают одну карточку правил", () => {
  setup();
  useHeroWindow.getState().show("state");
  render(<><HeroWindow /><EntityPopover /><RichText text="Состояние [[condition.frightened|испуганного]]" /></>);
  fireEvent.click(screen.getByRole("button", { name: "Испуганный" }));
  expect(screen.getByRole("dialog", { name: "Карточка: Испуганный" })).toBeTruthy();
  // Escape закрывает карточку, лист героя остаётся открыт.
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("dialog", { name: "Лист героя" })).toBeTruthy();
  expect(screen.queryByRole("dialog", { name: "Карточка: Испуганный" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /испуганного/ }));
  expect(screen.getByText(/проверки и атаки с помехой/)).toBeTruthy();
});
