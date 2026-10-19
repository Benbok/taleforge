import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatMessage } from "../lib/types";
import { useGame } from "../stores/game";
import MessageView from "./MessageView";

const send = vi.fn();
beforeEach(() => {
  useGame.setState(useGame.getInitialState(), true);
  useGame.setState({ socket: { send } as never });
  send.mockReset();
});
afterEach(cleanup);

const failed: ChatMessage = {
  id: "m1",
  seq: 3,
  kind: "action",
  seat_id: "seat_me",
  author: "Пупкинатор",
  content: "Съешь ягоду, тебе станет лучше",
  whisper: false,
  created_at: null,
  state: "failed",
};

it("retries my unprocessed reply without retyping it", () => {
  render(<MessageView m={failed} who={{ seats: {}, heroBySeat: {}, mySeat: "seat_me" }} />);
  expect(screen.getByText("не обработано")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
  expect(send).toHaveBeenCalledWith("message.retry", { message_id: "m1" });
});

it("does not offer to retry someone else's reply", () => {
  render(<MessageView m={failed} who={{ seats: {}, heroBySeat: {}, mySeat: "seat_other" }} />);
  expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
});
