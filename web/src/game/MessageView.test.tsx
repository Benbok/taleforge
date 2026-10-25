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

it('keeps an inline location link without adding a second location heading', () => {
  const message = { ...failed, kind: 'narration', whisper: true, scope: 'party', state: null,
    content: 'В [[gorge|Серой Глотке]] у тоннеля появился мост.', data: { location_ref: { id: 'gorge', name: 'Серая Глотка' } },
  } as ChatMessage;
  render(<MessageView m={message} who={{ seats: {}, heroBySeat: {}, mySeat: 'seat_me' }} />);
  expect(screen.queryByRole('button', { name: 'Серая Глотка' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Серой Глотке' })).toBeTruthy();
});

it("explains a transient provider failure and keeps the retry button", () => {
  const message = { ...failed, data: { action_failure: {
    category: "internal_error", code: "provider_error", message: "Провайдер модели не смог ответить.", retryable: true,
  } } } as ChatMessage;
  render(<MessageView m={message} who={{ seats: {}, heroBySeat: {}, mySeat: "seat_me" }} />);
  expect(screen.getByText("Провайдер модели не смог ответить.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Повторить" })).toBeTruthy();
});

it("shows a handled technical refusal instead of a success checkmark", () => {
  const message = { ...failed, state: 'answered', data: { action_failure: {
    category: 'unsupported_capability', code: 'unsupported_duration',
    message: 'Длительные эффекты пока не поддерживаются движком. Ресурсы не потрачены.',
  } } } as ChatMessage;
  render(<MessageView m={message} who={{ seats: {}, heroBySeat: {}, mySeat: 'seat_me' }} />);
  expect(screen.getByRole('status').textContent).toContain('не поддерживаются движком');
  expect(screen.queryByText('✓')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Повторить' })).toBeNull();
});

it("renders master narration in a distinct chronicle card with master heading", () => {
  const narration = { id: "n1", seq: 1, kind: "narration", content: "Лязг приближающейся нежити...", whisper: false } as ChatMessage;
  render(<MessageView m={narration} who={{ seats: {}, heroBySeat: {}, mySeat: "seat_me" }} />);
  expect(screen.getByText("Мастер")).toBeTruthy();
  expect(screen.getByText("Лязг приближающейся нежити...")).toBeTruthy();
});
