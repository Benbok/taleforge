import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { StatDetailCardContent, StatDetailTrigger } from "./StatDetailPopover";

describe("StatDetailPopover", () => {
  it("renders ability details card properly", () => {
    render(<StatDetailCardContent type="ability" id="str" />);
    expect(screen.getByText("Сила")).toBeDefined();
    expect(screen.getByText(/Strength/)).toBeDefined();
    expect(screen.getByText("Характеристика")).toBeDefined();
    expect(screen.getByText("Влияет на:")).toBeDefined();
    expect(screen.getByText(/Броски рукопашных атак/)).toBeDefined();
  });

  it("renders skill details card properly", () => {
    render(<StatDetailCardContent type="skill" id="athletics" />);
    expect(screen.getByText("Атлетика")).toBeDefined();
    expect(screen.getByText(/Сила \(СИЛ\)/)).toBeDefined();
    expect(screen.getByText("Примеры проверок:")).toBeDefined();
    expect(screen.getByText(/Взбирание по отвесной скале/)).toBeDefined();
    expect(screen.getByText(/Владение навыком прибавляет бонус мастерства/)).toBeDefined();
  });

  it("renders mastery details card properly", () => {
    render(<StatDetailCardContent type="mastery" />);
    expect(screen.getByText("Бонус мастерства")).toBeDefined();
    expect(screen.getByText("Правило")).toBeDefined();
    expect(screen.getByText("Где применяется:")).toBeDefined();
    expect(screen.getByText(/Навыки: если персонаж обучен навыку/)).toBeDefined();
  });

  it("renders trigger with children", () => {
    render(
      <StatDetailTrigger type="ability" id="dex">
        <span>Ловкость</span>
      </StatDetailTrigger>
    );
    expect(screen.getByText("Ловкость")).toBeDefined();
  });

  it("info button opens the card and does not toggle the skill checkbox", () => {
    let toggled = 0;
    render(
      <StatDetailTrigger type="skill" id="athletics" showIcon>
        <label>
          <input type="checkbox" onChange={() => toggled++} />
          Атлетика
        </label>
      </StatDetailTrigger>
    );
    fireEvent.click(screen.getByRole("button", { name: "Подробнее" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(toggled).toBe(0);
  });
});
