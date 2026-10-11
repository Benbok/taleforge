import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MasterLog from "./MasterLog";

vi.mock("../lib/api", () => ({ api: vi.fn(async () => ({
  secrets_visible: false, service_llm: [], turns: [{
    status: "done", seq: [1, 2], llm: [], combat: [], calls: [
      { tool: "roll_check", args: {}, ok: false, error: "Недоступны кубики", failure_code: "check_dice_failure", failure_category: "technical_safe", request_key: "abcdef1234567890" },
      { tool: "adjudicate_action", args: {}, ok: true, resolution_origin: "fallback", resolution_outcome: "partial", request_key: "abcdef1234567890" },
      { tool: "whisper", secret: true },
    ],
  }],
})) }));

afterEach(cleanup);

it("shows linked fallback diagnostics while retaining secret redaction", async () => {
  render(<QueryClientProvider client={new QueryClient()}><MasterLog campaignId="c" /></QueryClientProvider>);
  expect(await screen.findByText(/check_dice_failure/)).toBeTruthy();
  expect(screen.getByText(/technical_safe/)).toBeTruthy();
  expect(screen.getByText(/fallback.*partial/)).toBeTruthy();
  expect(screen.getAllByText(/abcdef123456/)).toHaveLength(2);
  expect(screen.getByText(/скрытое действие/)).toBeTruthy();
});
