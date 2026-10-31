import { fireEvent, screen, within } from "@testing-library/react";

/** jsdom не умеет showModal: оставляем у <dialog> только признак «открыт». Вызывается при импорте. */
function stubDialogs() {
  const proto = HTMLDialogElement.prototype;
  Object.defineProperty(proto, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(proto, "close", { configurable: true, value() { this.removeAttribute("open"); } });
}
stubDialogs();

/** Нажимает кнопку в общем окне подтверждения. */
export function answerConfirm(name: string | RegExp) {
  fireEvent.click(within(screen.getByRole("dialog", { hidden: true })).getByRole("button", { name, hidden: true }));
}
