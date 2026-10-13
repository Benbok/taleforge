export interface WorldSummary {
  id: string;
  name: string;
  version: string;
  category: string;
  summary: string;
  description: string;
  ruleset: string;
  ruleset_base?: string | null;
  level_cap: number;
  license?: string | null;
  badges: string[];
  status_badge: string;
  is_base: boolean;
  counts: Record<string, number>;
}

export interface LoreFactItem {
  id: string;
  name: string;
  text: string;
  tags: string[];
  doc?: string | null;
}

export interface LoreTopicGroup {
  topic: string;
  title: string;
  facts: LoreFactItem[];
}

export interface FactionItem {
  id: string;
  name: string;
  description: string;
  goal?: string | null;
  resources: string[];
  seat_ref?: string | null;
  leader_ref?: string | null;
  relations: { faction_ref: string; attitude: number; note?: string }[];
}

export interface LocationDistrict {
  name: string;
  text?: string | null;
}

export interface LocationItem {
  id: string;
  name: string;
  description: string;
  location_type?: string | null;
  population?: number | null;
  ruler?: string | null;
  belt?: string | null;
  districts: LocationDistrict[];
  tags: string[];
}

export interface OriginFeature {
  key?: string;
  name: string;
  description: string;
}

export interface OriginItem {
  id: string;
  name: string;
  epithet?: string | null;
  badge?: string | null;
  summary?: string | null;
  description: string;
  ability_bonuses: { ability?: string; value?: number; choose?: number; from?: string }[];
  formatted_bonuses?: string | null;
  highlights?: string[];
  features: OriginFeature[];
  speed?: number | null;
  speed_display?: string | null;
  size?: string | null;
  size_display?: string | null;
}

export interface ClassItem {
  id: string;
  name: string;
  epithet?: string | null;
  badge?: string | null;
  summary?: string | null;
  description: string;
  hit_die?: string | null;
  spell_source?: string | null;
  world_role?: string | null;
  highlights: string[];
  subclasses: { id: string; name: string; summary?: string }[];
}

export interface ScaleItem {
  id: string;
  name: string;
  description: string;
  widget_type?: string | null;
  min?: number | null;
  max?: number | null;
  tags: string[];
}

export interface ClockItem {
  id: string;
  name: string;
  description: string;
  scope?: string | null;
  min: number;
  max: number;
  moves_up: string[];
  moves_down: string[];
  thresholds: { at?: number; name?: string; text?: string }[];
}

export interface CreatureItem {
  id: string;
  name: string;
  description?: string | null;
  cr?: string | number | null;
  kind?: string | null;
  tags: string[];
}

export interface WorldDetail extends WorldSummary {
  lore_topics: LoreTopicGroup[];
  factions: FactionItem[];
  locations: LocationItem[];
  origins: OriginItem[];
  classes: ClassItem[];
  scales: ScaleItem[];
  clocks: ClockItem[];
  bestiary: CreatureItem[];
}
