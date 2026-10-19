import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { EquipmentResponse, HeroSheet } from "../lib/types";
import { useGame } from "../stores/game";
import Gear from "./Gear";

const sheet = {
  id: "ch_bran",
  name: "Бран",
  inventory: [
    { id: "inv_sword", item: "longsword", name: "Меч", qty: 1, equipped: false, category: "weapon", damage: { dice: "1d8", type: "рубящий" }, properties: ["versatile"] },
    { id: "inv_armor", item: "chain_mail", name: "Кольчуга", qty: 1, equipped: false, category: "armor", armor_type: "medium", ac_base: 16 },
  ],
  equipment: {
    can_manage: true,
    in_combat: true,
    changes: {
      inv_sword: { allowed: true, action_cost: 0, interaction_count: 1, displaced_ids: [] },
      inv_armor: { allowed: false, reason: "Доспех нельзя надеть в бою", action_cost: 0, interaction_count: 0, displaced_ids: [] },
    },
  },
} as unknown as HeroSheet;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useGame.getState().reset();
});

function setup() {
  useGame.setState({
    sheet,
    snapshot: { campaign: { id: "camp_1" } } as never,
    turn: { actor_id: sheet.id, round: 1, economy: { action: true, attacks_left: 1, bonus: true, move_left_ft: 30, disengage: false, interaction_free: true } } as never,
  });
}

it("показывает свойства, доступность и подсказку бесплатного взаимодействия", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => sheet }));
  setup();
  render(<Gear h={sheet} />);

  expect(screen.getByText("Меч")).toBeTruthy();
  expect(screen.getByText("1d8 рубящий")).toBeTruthy();
  expect(screen.getByText("универсальное")).toBeTruthy();
  expect(screen.getByText("средняя броня, КД 16")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Взять: Меч" }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByText("бесплатно")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Надеть: Кольчуга" }).hasAttribute("disabled")).toBe(true);
});

it("отправляет изменение и обновляет лист ответом сервера", async () => {
  const updated = { ...sheet, inventory: sheet.inventory.map((item) => item.id === "inv_sword" ? { ...item, equipped: true } : item) } as HeroSheet;
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ status: 200, ok: true, json: async () => sheet })
    .mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({ character: updated, economy: null } satisfies EquipmentResponse) });
  vi.stubGlobal("fetch", fetchMock);
  setup();
  render(<Gear h={sheet} />);

  fireEvent.click(screen.getByRole("button", { name: "Взять: Меч" }));
  await waitFor(() => expect(useGame.getState().sheet?.inventory.find((item) => item.id === "inv_sword")?.equipped).toBe(true));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/campaigns/camp_1/characters/ch_bran/equipment",
    expect.objectContaining({ method: "PUT" }),
  );
});
