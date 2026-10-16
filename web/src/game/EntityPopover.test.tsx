import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useGame } from "../stores/game";
import { useDraft } from "./draft";
import { useInspector } from "./inspector";

const sent: unknown[] = [];
vi.mock("./quick", () => ({
  attack: vi.fn(),
  sendQuick: (text: string, actions: unknown[]) => {
    sent.push({ text, actions });
    return null;
  },
}));

const { default: EntityPopover, Container } = await import("./EntityPopover");

afterEach(() => {
  cleanup();
  sent.length = 0;
  useInspector.getState().close();
});

it("осмотр по ссылке сохраняет ID выбранного пепелища в черновике", () => {
  useDraft.setState({ text: "", quick: null, campaignId: null });
  useGame.setState({ cards: { pyre: { id: "pyre", type: "landmark", name: "Старое пепелище" } } });
  useInspector.setState({ id: "pyre", label: "Старое пепелище", anchor: null });
  render(<EntityPopover />);
  fireEvent.click(screen.getByRole("button", { name: "Осмотреть" }));
  expect(useDraft.getState().text).toBe("Осматриваю: Старое пепелище");
  expect(useDraft.getState().quick).toEqual([{ verb: "inspect", target_id: "pyre" }]);
});

describe("контейнер в карточке", () => {
  it("показывает состояние и шлёт те же намерения, что фраза в чате", () => {
    useGame.setState({ actions: ["chat.play"] });
    const done = vi.fn();
    render(<Container id="en1" name="Сундук" state={{ open: false, locked: false, contents: "unexamined" }} onDone={done} />);
    expect(screen.getByText("закрыт")).toBeTruthy();
    expect(screen.getByText(/не исследован/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Открыть" }));
    fireEvent.click(screen.getByRole("button", { name: "Обыскать" }));
    expect(sent).toEqual([
      { text: "Открываю: Сундук", actions: [{ verb: "interact", target_id: "en1" }] },
      { text: "Обыскиваю: Сундук", actions: [{ verb: "search", target_id: "en1" }] },
    ]);
    expect(done).toHaveBeenCalledTimes(2);
  });

  it("пока содержимое готовится, обыск недоступен с причиной; открытому не нужна кнопка «Открыть»", () => {
    useGame.setState({ actions: ["chat.play"] });
    render(<Container id="en1" name="Шкаф" state={{ open: true, locked: false, contents: "pending" }} onDone={() => {}} />);
    expect(screen.queryByRole("button", { name: "Открыть" })).toBeNull();
    const search = screen.getByRole("button", { name: "Обыскать" }) as HTMLButtonElement;
    expect(search.disabled).toBe(true);
    expect(search.title).toBe("Содержимое ещё готовится");
    expect(screen.getByText(/готовится…/)).toBeTruthy();
  });

  it("без права действовать — только состояние", () => {
    useGame.setState({ actions: [] });
    render(<Container id="en1" name="Сундук" state={{ open: false, locked: true, contents: "blocked" }} onDone={() => {}} />);
    expect(screen.getByText("заперт")).toBeTruthy();
    expect(screen.getByText(/недоступно/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
