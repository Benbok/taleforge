import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useGame } from "../stores/game";
import type { HeroSheet } from "../lib/types";
import EntityPopover from "./EntityPopover";
import RichText from "./RichText";
import { useInspector } from "./inspector";

afterEach(() => {
  cleanup();
  useInspector.getState().close();
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

it("ссылка на эффект открывает карточку и закрывается по Escape", () => {
  setup();
  render(<><EntityPopover /><RichText text="Состояние [[condition.frightened|испуганного]]" /></>);
  fireEvent.click(screen.getByRole("button", { name: /испуганного/ }));
  expect(screen.getByRole("dialog", { name: "Карточка: Испуганный" })).toBeTruthy();
  expect(screen.getByText(/проверки и атаки с помехой/)).toBeTruthy();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "Карточка: Испуганный" })).toBeNull();
});
