import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useGame } from "../stores/game";
import Composer from "./Composer";
import { useDraft } from "./draft";

let client: QueryClient;
beforeEach(() => {
  useGame.setState(useGame.getInitialState(), true);
  useDraft.setState(useDraft.getInitialState(), true);
  useGame.setState({ actions: ["chat.play", "chat.ooc"], myPending: { id: "reply", created_at: new Date().toISOString() } });
  client = new QueryClient();
  client.setQueryData(["voice"], { enabled: false });
});
afterEach(() => { cleanup(); client.clear(); vi.useRealTimers(); });

const open = () => render(<QueryClientProvider client={client}><Composer /></QueryClientProvider>);

it("кнопка отправки сохраняет ID объекта из карточки", () => {
  const send = vi.fn(() => true);
  useGame.setState({ connection: "open", socket: { send } as never, myPending: null });
  useDraft.getState().insert("Осматриваю: Старое пепелище", { verb: "inspect", target_id: "pyre" });
  open();
  fireEvent.click(screen.getByRole("button", { name: /^Отправить/ }));
  expect(send).toHaveBeenCalledWith("message.send", expect.objectContaining({
    text: "Осматриваю: Старое пепелище", quick: { actions: [{ verb: "inspect", target_id: "pyre" }] },
  }));
  expect(useDraft.getState().quick).toBeNull();
});

describe("статус ответа мастера", () => {
  it("скрывает ожидание игроков при начале ответа и не дублирует статус мастера над полем", () => {
    open();
    expect(screen.getByText("Ожидаем остальных игроков")).toBeDefined();
    act(() => useGame.setState({ masterStage: "describing" }));
    expect(screen.queryByText("Мастер отвечает")).toBeNull();
    expect(screen.queryByText("Ожидаем остальных игроков")).toBeNull();
  });
  it("показывает пояснение после 30 секунд и убирает его после ответа", () => {
    vi.useFakeTimers();
    useGame.setState({ masterStage: "remembering" });
    open();
    expect(screen.queryByText(/Ответ занимает больше времени/)).toBeNull();
    act(() => vi.advanceTimersByTime(30000));
    expect(screen.getByText(/Повторно отправлять реплику не нужно/)).toBeDefined();
    act(() => useGame.setState({ masterStage: null, myPending: null }));
    expect(screen.queryByText(/Ответ занимает больше времени/)).toBeNull();
  });
});

it("показывает активные эффекты, форму куста и оставшееся время над полем ввода", () => {
  useGame.setState({
    sheet: {
      name: "Ива",
      exploration: {
        game_seconds: "24",
        effects: [
          { id: "camouflage", kind: "camouflage", label: "Маскировка в тени руин", remaining_seconds: "18" },
          { id: "light", kind: "illumination", label: "Светлячки", remaining_seconds: "45" },
        ],
        constraints: { form: "Облик крысы" },
      },
    } as never,
    myPending: null,
  });
  open();
  expect(screen.getByText("Маскировка в тени руин")).toBeDefined();
  expect(screen.getByText(/18 с/)).toBeDefined();
  expect(screen.getByText("Светлячки")).toBeDefined();
  expect(screen.getByText(/45 с/)).toBeDefined();
  expect(screen.queryByText(/без движений и речи/)).toBeNull(); // what a form allows is not the UI's call
});

it("открывает меню быстрых действий по кнопке ⚡ и вставляет выбранное действие", () => {
  open();
  const boltBtn = screen.getByRole("button", { name: "Быстрые действия" });
  expect(boltBtn).toBeDefined();
  expect(screen.queryByRole("menu")).toBeNull();

  // Открываем меню
  fireEvent.click(boltBtn);
  expect(screen.getByRole("menu")).toBeDefined();

  // Выбираем действие "Осмотреться"
  const inspectBtn = screen.getByRole("menuitem", { name: /Осмотреться/ });
  fireEvent.click(inspectBtn);

  // Меню закрылось, текст подставился в draft
  expect(screen.queryByRole("menu")).toBeNull();
  expect(useDraft.getState().text).toContain("Внимательно осматриваюсь вокруг");
});
