import type { components } from './api.gen';

export type HeroCard = components['schemas']['HeroCard'];
export type HeroDescription = components['schemas']['HeroDescription'];
export type HeroEdit = components['schemas']['HeroEdit'];
export type StartingEquipment = components['schemas']['StartingEquipment'];
export type AbilityKey = 'str' | 'dex' | 'con' | 'int' | 'wis' | 'cha';
export const abilityNames: Record<AbilityKey, string> = {
  str: 'Сила', dex: 'Ловкость', con: 'Телосложение', int: 'Интеллект', wis: 'Мудрость', cha: 'Харизма',
};
export const abilityKeys = Object.keys(abilityNames) as AbilityKey[];
export const energyThemes: Record<string, { color: string; label: string; short: string }> = {
  str: { color: 'var(--tf-ember)', label: 'Физический ресурс', short: 'СИЛ' },
  dex: { color: 'var(--tf-patina)', label: 'Импульс и реакция', short: 'ЛОВ' },
  int: { color: 'color-mix(in srgb, #38bdf8 70%, var(--tf-accent))', label: 'Концентрация', short: 'ИНТ' },
  wis: { color: 'color-mix(in srgb, #a855f7 70%, var(--tf-patina))', label: 'Интуиция и дух', short: 'МДР' },
  cha: { color: 'var(--tf-accent)', label: 'Сила воли и влияние', short: 'ХАР' },
};
export const emptyDescription: HeroDescription = { name: '', identity: '', appearance: '', personality: '', capabilities: '' };
export interface HeroDialogue {
  id: string; revision: number; status: string; description: HeroDescription;
  campaign_id: string | null; hero_id: string | null;
  transcript: { role: string; content?: string }[];
  proposal: { abilities: Record<AbilityKey, string>; explanations: Record<AbilityKey, string>; equipment?: StartingEquipment | null } | null;
}
export interface EditProposal { id: string; edit: HeroEdit; explanations: Record<AbilityKey, string> }

export function universalCard(value: unknown): HeroCard | null {
  if (!value || typeof value !== 'object') return null;
  const card = value as HeroCard;
  return card.sheet?.rules_version === 'universal.v1' ? card : null;
}
