import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { EquipmentResponse, HeroSheet } from "../lib/types";
import { DAMAGE_RU } from "./hero";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";

const CATEGORY_RU: Record<string, string> = {
  weapon: "оружие",
  armor: "броня",
  consumable: "расходник",
  gear: "снаряжение",
};

const PROPERTY_RU: Record<string, string> = {
  ammunition: "боеприпасы",
  finesse: "фехтовальное",
  heavy: "тяжёлое",
  light: "лёгкое",
  loading: "перезарядка",
  reach: "досягаемость",
  thrown: "метательное",
  two_handed: "двуручное",
  versatile: "универсальное",
};

const ARMOR_RU: Record<string, string> = {
  light: "лёгкая броня",
  medium: "средняя броня",
  heavy: "тяжёлая броня",
  shield: "щит",
};

function actionLabel(equipped: boolean, category?: string | null): string | null {
  if (category === "weapon") return equipped ? "Снять" : "Взять";
  if (category === "armor") return equipped ? "Снять" : "Надеть";
  return null;
}

function changeHint(h: HeroSheet, id: string): string | null {
  const change = h.equipment?.changes?.[id];
  if (!change || !h.equipment?.in_combat) return null;
  if (!change.allowed) return change.reason ?? "Смена сейчас недоступна";
  const cost = change.action_cost ?? 0;
  if (cost === 0 && (change.interaction_count ?? 0) > 0) return "бесплатно";
  if (cost === 1) return "потратит действие";
  if (cost > 1) return `потратит ${cost} действия`;
  return null;
}

function Gear({ h }: { h: HeroSheet }) {
  const campaignId = useGame((s) => s.snapshot?.campaign.id ?? null);
  const playAs = useGame((s) => s.playAs);
  const turn = useGame((s) => s.turn);
  const setSheet = useGame((s) => s.setSheet);
  const [pending, setPending] = useState<string | null>(null);

  const turnKey = [
    turn?.actor_id,
    turn?.round,
    turn?.economy?.action,
    turn?.economy?.interaction_free,
    turn?.economy?.attacks_left,
    turn?.economy?.bonus,
    turn?.economy?.move_left_ft,
  ].join(":");

  useEffect(() => {
    if (!campaignId || !h.id) return;
    let live = true;
    const query = playAs ? `?as_seat=${encodeURIComponent(playAs)}` : "";
    void api<HeroSheet>(`/api/campaigns/${campaignId}/characters/${h.id}${query}`)
      .then((fresh) => {
        if (live && useGame.getState().sheet?.id === h.id) setSheet(fresh);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
    // The sheet itself is deliberately absent: applying this request must not
    // trigger another request loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, h.id, playAs, turnKey]);

  async function toggle(item: HeroSheet["inventory"][number]) {
    if (!campaignId || pending || !h.equipment?.can_manage) return;
    const change = h.equipment.changes?.[item.id];
    if (!change?.allowed) return;
    setPending(item.id);
    const query = playAs ? `?as_seat=${encodeURIComponent(playAs)}` : "";
    try {
      const response = await api<EquipmentResponse>(
        `/api/campaigns/${campaignId}/characters/${h.id}/equipment${query}`,
        { method: "PUT", body: { inventory_id: item.id, equipped: !item.equipped } },
      );
      if (useGame.getState().sheet?.id === h.id) setSheet(response.character as HeroSheet);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось изменить снаряжение");
    } finally {
      setPending(null);
    }
  }

  if (!h.inventory.length) return <p className="text-muted">Снаряжения нет.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {h.inventory.map((i) => {
        const label = actionLabel(i.equipped, i.category);
        const change = h.equipment?.changes?.[i.id];
        const hint = changeHint(h, i.id);
        const disabled = !label || !h.equipment?.can_manage || !change?.allowed || pending !== null;
        return (
          <li key={i.id} className="flex flex-col gap-1 border-b border-line py-2">
            <div className="flex items-start justify-between gap-2">
              <span>
                <span className="font-medium">{i.name}</span>
                {i.qty > 1 ? ` ×${i.qty}` : ""}
                {i.equipped && <span className="ml-2 text-xs text-accent">надето</span>}
              </span>
              {label && (
                <button
                  className="btn shrink-0 px-2 py-1 text-xs"
                  disabled={disabled}
                  aria-label={`${label}: ${i.name}`}
                  title={change?.reason ?? hint ?? undefined}
                  onClick={() => void toggle(i)}
                >
                  {pending === i.id ? "…" : label}
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-x-3 text-xs text-muted">
              {i.category && <span>{CATEGORY_RU[i.category] ?? i.category}</span>}
              {i.damage && <span>{i.damage.dice} {DAMAGE_RU[i.damage.type] ?? i.damage.type}</span>}
              {i.properties?.length ? <span>{i.properties.map((p) => PROPERTY_RU[p] ?? p).join(", ")}</span> : null}
              {i.armor_type && (
                <span>
                  {ARMOR_RU[i.armor_type] ?? i.armor_type}
                  {i.ac_base != null ? `, КД ${i.ac_base}` : ""}
                </span>
              )}
              {i.ac_bonus != null && <span>+{i.ac_bonus} к КД</span>}
            </div>
            {hint && <p className={`text-xs ${change?.allowed ? "text-muted" : "text-warn"}`}>{hint}</p>}
          </li>
        );
      })}
    </ul>
  );
}

export default Gear;
