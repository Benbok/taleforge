import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { Room } from "../lib/campaign";
import SettingsTab from "./SettingsTab";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function room(ruleset_id: string): Room {
  return {
    id: "c1", name: "Кампания", status: "active", owner_id: "u", is_owner: true, my_seat_id: null, my_role: "master",
    pack_id: null, difficulty: "normal", party_size_recommended: 4, public_intro: "Афиша", ruleset_id,
    settings: {}, seats: [],
  } as unknown as Room;
}

function show(r: Room) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <SettingsTab room={r} onRoom={() => {}} />
  </MemoryRouter></QueryClientProvider>);
}

const dormant = [/Сложность вызовов/, /Рост уровней/, /Случайности в пути/, /Время на ход в бою/, /Запретные темы/];
const working = [/Название кампании/, /Публичная вводная/, /Окно сбора реплик/, /Лимит расходов/];

it("в универсальной кампании не показывает настройки, которые пока ничего не делают", () => {
  show(room("universal"));
  for (const label of dormant) expect(screen.queryByText(label)).toBeNull();
  for (const label of working) expect(screen.getByText(label)).toBeTruthy();
});

it("в остальных кампаниях показывает все настройки стола", () => {
  show(room("dnd5e"));
  for (const label of [...dormant, ...working]) expect(screen.getByText(label)).toBeTruthy();
});
