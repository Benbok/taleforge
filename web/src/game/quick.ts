// Быстрые действия: намерение собрано кнопками (цель и оружие по id), модель его не разбирает, но сервер
// проверяет тем же валидатором. Реплика в чате — обычным текстом, чтобы мастер и другие игроки её видели.
import type { HeroAttack } from "../lib/types";
import { useGame } from "../stores/game";

export interface QuickAction {
  verb: string;
  target_id?: string | null;
  instrument_id?: string | null;
  skill?: string | null;
  spell_id?: string | null;
  slot_level?: number | null;
  ritual?: boolean;
  /** Площадное заклинание: кого накрывает область. */
  target_ids?: string[];
  /** Цель, которой нет в списке сцены, словами игрока: её заводит мастер. */
  free_target?: string;
  manner?: string;
}

let n = 0;

/** Отправляет быстрое действие. Возвращает причину, если отправить нельзя, иначе null. */
export function sendQuick(text: string, actions: QuickAction[]): string | null {
  const g = useGame.getState();
  if (!g.actions.includes("chat.play")) return g.blocked["chat.play"] ?? "Сейчас действовать нельзя.";
  if (g.connection !== "open" || !g.socket) return "Нет связи с сервером.";
  const clientId = `q${Date.now().toString(36)}${(n++).toString(36)}`;
  if (!g.socket.send("message.send", { kind: "action", text, client_id: clientId, quick: { actions } }))
    return "Нет связи с сервером.";
  g.addPending({ clientId, text, whisper: false, at: Date.now() });
  return null;
}

export function attackText(target: string, a: HeroAttack): string {
  return a.key === "unarmed" ? `Бью без оружия: ${target}` : `Атакую: ${target} (${a.name.toLowerCase()})`;
}

export function attack(targetId: string, targetName: string, a: HeroAttack): string | null {
  return sendQuick(attackText(targetName, a), [
    { verb: "attack", target_id: targetId, instrument_id: a.inventory_id ?? null },
  ]);
}

/** Заклинание из окна сотворения: цели, ячейка и «как именно» уже выбраны игроком. */
export function cast(plan: {
  spellId: string;
  text: string;
  targets: string[];
  other: string | null;
  area: boolean;
  slot: number | null;
  ritual: boolean;
  manner: string;
}): string | null {
  return sendQuick(plan.text, [
    {
      verb: "cast",
      spell_id: plan.spellId,
      target_id: plan.area || plan.other !== null ? null : (plan.targets[0] ?? null),
      target_ids: plan.area ? plan.targets : [],
      free_target: plan.other?.trim().slice(0, 300) ?? "",
      slot_level: plan.slot,
      ritual: plan.ritual,
      manner: plan.manner.trim().slice(0, 300),
    },
  ]);
}
