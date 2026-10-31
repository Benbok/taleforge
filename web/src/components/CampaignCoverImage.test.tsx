import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CampaignCoverImage from "./CampaignCoverImage";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, blob: async () => new Blob(["x"]) }) as Response));
  URL.createObjectURL = vi.fn(() => "blob:cover");
  URL.revokeObjectURL = vi.fn();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("открывает обложку на весь экран и закрывает по кнопке", async () => {
  render(<CampaignCoverImage url="/c" name="Мир" expandable />);
  fireEvent.click(await screen.findByRole("button", { name: /на весь экран/ }));
  expect(screen.getByRole("dialog", { hidden: true, name: "Обложка мира «Мир»" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Закрыть иллюстрацию", hidden: true }));
  expect(document.querySelector("[data-artwork-viewer]")).toBeNull();
});

it("без expandable остаётся обычной картинкой", async () => {
  render(<CampaignCoverImage url="/c" name="Мир" />);
  await screen.findByAltText("Обложка мира «Мир»");
  expect(screen.queryByRole("button")).toBeNull();
});
