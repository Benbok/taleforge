import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import MobileHeroSheet from "./MobileHeroSheet";

const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});
afterAll(() => {
  if (originalShow) Object.defineProperty(HTMLDialogElement.prototype, "showModal", originalShow);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  if (originalClose) Object.defineProperty(HTMLDialogElement.prototype, "close", originalClose);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
});
afterEach(() => { cleanup(); document.body.style.overflow = ""; });

describe("мобильная сводка героя", () => {
  it("открывается поверх шага, закрывается и возвращает фокус", () => {
    document.body.style.overflow = "auto";
    render(<MobileHeroSheet summary="КД 12"><p>Характеристики героя</p></MobileHeroSheet>);
    const trigger = screen.getByRole("button", { name: /Лист героя/ });
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Сводка героя" })).toBeDefined();
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("auto");
    expect(document.activeElement).toBe(trigger);
  });
  it("закрывается при отмене диалога клавишей Escape", () => {
    render(<MobileHeroSheet summary="КД 12">Сводка</MobileHeroSheet>);
    fireEvent.click(screen.getByRole("button", { name: /Лист героя/ }));
    fireEvent(screen.getByRole("dialog"), new Event("cancel"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
