import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PassageBar } from "./PassageBar";

describe("панель прохода", () => {
  it("показывает неизвестное назначение и не открывает дверь оптимистически", () => {
    const onTraverse = vi.fn();
    render(<PassageBar exit={{ name: "Тропа", kind: "gap", side: "e", at: 1, state: "closed", width: 2 }} onTraverse={onTraverse} />);
    expect(screen.getByText("Неизвестное место")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Подойти" })).not.toBeNull();
    const move = screen.getByRole("button", { name: "Перейти" }) as HTMLButtonElement;
    expect(move.disabled).toBe(true);
    fireEvent.click(move);
    expect(onTraverse).not.toHaveBeenCalled();
  });
});
