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
  it("заменяет ожидание игроков при начале ответа", () => {
    open();
    expect(screen.getByText("Ожидаем остальных игроков")).toBeDefined();
    act(() => useGame.setState({ masterStage: "describing" }));
    expect(screen.getByText("Мастер отвечает")).toBeDefined();
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
