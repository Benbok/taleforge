import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export interface Call {
  url: string;
  method: string;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body: unknown } | undefined;

/** Подменяет fetch и запоминает запросы; WebSocket запрещён: авторский просмотр не должен открывать игровой сокет. */
export function mockApi(handler: Handler) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const call: Call = { url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const out = handler(call) ?? { status: 404, body: { detail: "нет обработчика" } };
    const status = out.status ?? 200;
    return { ok: status < 400, status, json: async () => out.body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  const socket = vi.fn(() => {
    throw new Error("авторский просмотр не должен открывать сокет");
  });
  vi.stubGlobal("WebSocket", socket);
  return { calls, socket };
}

export function renderWithClient(ui: ReactElement, client = new QueryClient({ defaultOptions: { queries: { retry: false } } }), route = "/") {
  return { client, ...render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  ) };
}
