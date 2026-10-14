import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChoiceCard } from "./ChoiceDetails";

afterEach(() => vi.useRealTimers());

describe("подробности выбора", () => {
  it("открываются только кнопкой, сохраняются после ухода мыши и закрываются по Escape", () => {
    vi.useFakeTimers();
    const onPick = vi.fn();
    render(<ChoiceCard name="Воин" selected={false} onPick={onPick} className="" details={<p>Описание воина</p>}><span>Воин</span></ChoiceCard>);
    const card = screen.getByRole("radio");
    const mouse = new Event("pointerover", { bubbles: true });
    Object.defineProperty(mouse, "pointerType", { value: "mouse" });
    fireEvent(card, mouse);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Подробнее: Воин" }));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.pointerLeave(card, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("dialog")).toBeDefined();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
