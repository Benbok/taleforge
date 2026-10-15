import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Room, Seat } from "../lib/campaign";
import PlayersTab from "./PlayersTab";

const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

function makeSeats(playerCount: number, emptyCount = 0): Seat[] {
  const seats: Seat[] = [
    { id: "s_master", role: "master", position: 0, occupant_type: "human", user_id: "u_m", user_name: "Мастер" },
  ];
  for (let i = 1; i <= playerCount; i++) {
    const isEmpty = i > playerCount - emptyCount;
    seats.push({
      id: `s_p${i}`,
      role: "player",
      position: i,
      occupant_type: isEmpty ? "empty" : "human",
      user_id: isEmpty ? null : `u_${i}`,
      user_name: isEmpty ? null : `Игрок ${i}`,
    });
  }
  return seats;
}

function makeRoom(overrides: Partial<Room> = {}): Room {
  return {
    id: "c1",
    name: "Кампания",
    status: "lobby",
    owner_id: "u_owner",
    is_owner: true,
    my_seat_id: "s_master",
    my_role: "master",
    pack_id: "world",
    difficulty: "medium",
    party_size_recommended: 4,
    public_intro: "Вступление",
    settings: {},
    brief: null,
    seats: makeSeats(3, 1),
    ...overrides,
  };
}

const clients: QueryClient[] = [];
function renderTab(room: Room, onRoom = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(qc);
  return {
    ...render(
      <QueryClientProvider client={qc}>
        <PlayersTab room={room} onRoom={onRoom} />
      </QueryClientProvider>,
    ),
    onRoom,
  };
}

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((qc) => qc.clear());
  vi.unstubAllGlobals();
});

describe("PlayersTab — расширение мест и правила допуска", () => {
  it("отображает сводку мест и текст правил допуска в лобби", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (path === "/api/campaigns/c1/characters") {
          return response([
            { id: "ch1", seat_id: "s_p1", name: "Арагорн", status: "approved" },
            { id: "ch2", seat_id: "s_p2", name: "Гимли", status: "draft" },
          ]);
        }
        if (path === "/api/campaigns/c1/party-roles") {
          return response({ heroes: 1, recommended: 4, have: [], missing: [] });
        }
        if (path === "/api/campaigns/c1/invites") return response([]);
        return response([]);
      }),
    );

    renderTab(makeRoom({ status: "lobby" }));

    expect(await screen.findByText(/Мест: 3 из 6 · Свободно: 1 · Героев в игре: 1/)).toBeDefined();
    expect(screen.getByText("Вступление героев открыто (до старта сессии)")).toBeDefined();
  });

  it("отображает правила допуска на паузе и при активной сессии", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (path === "/api/campaigns/c1/party-roles") {
          return response({ heroes: 0, recommended: 4, have: [], missing: [] });
        }
        return response([]);
      }),
    );

    const { rerender } = renderTab(makeRoom({ status: "paused" }));
    expect(screen.getByText(/Новый герой вступает в текущую локацию сцены/)).toBeDefined();
    expect(await screen.findByText("Вступление героев доступно на паузе (вне боя и ходов мастера)")).toBeDefined();

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    clients.push(qc);
    rerender(
      <QueryClientProvider client={qc}>
        <PlayersTab room={makeRoom({ status: "active" })} onRoom={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Идёт сессия: новые герои могут вступить на паузе")).toBeDefined();
  });

  it("показывает активную кнопку '+ ДОБАВИТЬ МЕСТО ИГРОКА' для владельца при < 6 мест", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response([])),
    );

    renderTab(makeRoom({ is_owner: true, seats: makeSeats(3) }));

    const btn = await screen.findByRole("button", { name: /\+ ДОБАВИТЬ МЕСТО ИГРОКА/ });
    expect(btn).toBeDefined();
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("дизейблит кнопку '+ ДОБАВИТЬ МЕСТО ИГРОКА' при достижении 6 мест", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response([])),
    );

    renderTab(makeRoom({ is_owner: true, seats: makeSeats(6) }));

    const btn = await screen.findByRole("button", { name: /\+ ДОБАВИТЬ МЕСТО ИГРОКА/ });
    expect(btn).toBeDefined();
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("не показывает кнопку '+ ДОБАВИТЬ МЕСТО ИГРОКА' для не-владельца или при статусе ended", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response([])),
    );

    const { rerender } = renderTab(makeRoom({ is_owner: false }));
    expect(screen.queryByRole("button", { name: /\+ ДОБАВИТЬ МЕСТО ИГРОКА/ })).toBeNull();

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    clients.push(qc);
    rerender(
      <QueryClientProvider client={qc}>
        <PlayersTab room={makeRoom({ is_owner: true, status: "ended" })} onRoom={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button", { name: /\+ ДОБАВИТЬ МЕСТО ИГРОКА/ })).toBeNull();
  });

  it("отправляет POST /api/campaigns/:id/seats и обновляет комнату по клику", async () => {
    const updatedRoom = makeRoom({ seats: makeSeats(4) });
    const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/campaigns/c1/seats" && init?.method === "POST") {
        return response(updatedRoom);
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetcher);

    const { onRoom } = renderTab(makeRoom({ is_owner: true, seats: makeSeats(3) }));
    const btn = await screen.findByRole("button", { name: /\+ ДОБАВИТЬ МЕСТО ИГРОКА/ });
    fireEvent.click(btn);

    await waitFor(() => expect(onRoom).toHaveBeenCalledWith(updatedRoom));
    expect(fetcher).toHaveBeenCalledWith("/api/campaigns/c1/seats", expect.objectContaining({ method: "POST" }));
  });
});
