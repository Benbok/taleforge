import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useDraft } from "./draft";
import { StepBar } from "./MapWindow";

afterEach(() => {
  cleanup();
  useDraft.setState({ campaignId: null, text: "" });
});

describe("подход к объекту на карте", () => {
  it("не отправляет выдуманную клетку в map.step для условного маркера", () => {
    const go = vi.fn();
    const onClose = vi.fn();
    render(
      <StepBar
        pick={{ name: "Скелет", near: [[12, -3]], precise: false }}
        go={go}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Подойти словами" }));
    expect(go).not.toHaveBeenCalled();
    expect(useDraft.getState().text).toBe("Подхожу к «Скелет».");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("отправляет реальную клетку точного маркера движку", () => {
    const go = vi.fn();
    const onClose = vi.fn();
    render(
      <StepBar
        pick={{ name: "Скелет", near: [[2, 4]], precise: true }}
        go={go}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Подойти" }));
    expect(go).toHaveBeenCalledTimes(1);
    expect(go).toHaveBeenCalledWith({ near: [[2, 4]] });
    expect(useDraft.getState().text).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });
});
