import type { components } from './api.gen';

export type HeroCard = components['schemas']['HeroCard'];
export type HeroDescription = components['schemas']['HeroDescription'];
export type HeroEdit = components['schemas']['HeroEdit'];
export type AbilityKey = 'str' | 'dex' | 'con' | 'int' | 'wis' | 'cha';
export const abilityNames: Record<AbilityKey, string> = {
  str: 'Сила', dex: 'Ловкость', con: 'Телосложение', int: 'Интеллект', wis: 'Мудрость', cha: 'Харизма',
};
export const abilityKeys = Object.keys(abilityNames) as AbilityKey[];
export const emptyDescription: HeroDescription = { name: '', identity: '', appearance: '', personality: '', capabilities: '' };
export interface HeroDialogue {
  id: string; revision: number; status: string; description: HeroDescription;
  campaign_id: string | null; hero_id: string | null;
  transcript: { role: string; content?: string }[];
  proposal: { abilities: Record<AbilityKey, string>; explanations: Record<AbilityKey, string> } | null;
}
export interface EditProposal { id: string; edit: HeroEdit; explanations: Record<AbilityKey, string> }

export function universalCard(value: unknown): HeroCard | null {
  if (!value || typeof value !== 'object') return null;
  const card = value as HeroCard;
  return card.sheet?.rules_version === 'universal.v1' ? card : null;
}
