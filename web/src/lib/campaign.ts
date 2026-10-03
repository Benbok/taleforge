// РљР°РјРїР°РЅРёСЏ РІРЅРµ РёРіСЂС‹: СЃРѕР·РґР°РЅРёРµ РїРѕ С€Р°РіР°Рј, РєР°Р±РёРЅРµС‚ РІР»Р°РґРµР»СЊС†Р°, РЅР°СЃС‚СЂРѕР№РєРё РјР°СЃС‚РµСЂР°. РџРѕРґРїРёСЃРё РІР°СЂРёР°РЅС‚РѕРІ РїСЂРёС…РѕРґСЏС‚
// СЃ СЃРµСЂРІРµСЂР° (/api/campaign-options), Р·РґРµСЃСЊ С‚РѕР»СЊРєРѕ С‚РёРїС‹ Рё С‚Рѕ, С‡С‚Рѕ СЃРѕР±РёСЂР°РµС‚ Р·Р°РїСЂРѕСЃС‹.

export interface Seat {
  id: string;
  role: "master" | "player";
  position: number;
  occupant_type: "human" | "agent" | "empty";
  user_id: string | null;
  user_name: string | null;
  agent_provider?: string | null;
}

export interface Brief {
  length?: string;
  threat?: string;
  pillars?: Record<string, string>;
  emotions?: string[];
  wishes?: string;
}

/** РљР°РјРїР°РЅРёСЏ, РєР°Рє РµС‘ РІРёРґРёС‚ СѓС‡Р°СЃС‚РЅРёРє (GET /api/campaigns/{id}). brief вЂ” С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»СЊС†Сѓ Рё РјР°СЃС‚РµСЂСѓ. */
export interface Room {
  id: string;
  name: string;
  status: string;
  owner_id: string;
  is_owner: boolean;
  my_seat_id: string | null;
  my_role: "master" | "player" | null;
  pack_id: string | null;
  difficulty: string;
  party_size_recommended: number;
  public_intro: string;
  settings: {
    turn_timeout_sec?: number;
    collect_window_sec?: number;
    spend_limit_usd?: number | null;
    excluded_themes?: string[];
    audio_enabled?: boolean;
    tts_provider?: string;
    tts_enabled?: boolean;
    tts_voice?: string | null;
    leveling?: "xp" | "milestone";
    random_events?: "auto" | "manual";
    poster?: Poster | null;
    [k: string]: unknown;
  };
  brief: Brief | null;
  seats: Seat[];
}

export interface TtsVoiceOption {
  id: string;
  name: string;
  gender: "РјСѓР¶СЃРєРѕР№" | "Р¶РµРЅСЃРєРёР№" | "СѓРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№";
  description: string;
}

export const TTS_VOICES: TtsVoiceOption[] = [
  { id: "Fenrir", name: "Fenrir", gender: "РјСѓР¶СЃРєРѕР№", description: "Р“Р»СѓР±РѕРєРёР№, РїРѕРІРµСЃС‚РІРѕРІР°С‚РµР»СЊРЅС‹Р№ С‚РѕРЅ (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ)" },
  { id: "Charon", name: "Charon", gender: "РјСѓР¶СЃРєРѕР№", description: "РќРёР·РєРёР№, РјСЂР°С‡РЅС‹Р№, С‚Р°РёРЅСЃС‚РІРµРЅРЅС‹Р№" },
  { id: "Puck", name: "Puck", gender: "СѓРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№", description: "Р–РёРІРѕР№, РѕР·РѕСЂРЅРѕР№, РІС‹СЂР°Р·РёС‚РµР»СЊРЅС‹Р№" },
  { id: "Kore", name: "Kore", gender: "Р¶РµРЅСЃРєРёР№", description: "РЎРїРѕРєРѕР№РЅС‹Р№, РјСЏРіРєРёР№, Р°С‚РјРѕСЃС„РµСЂРЅС‹Р№" },
  { id: "Aoede", name: "Aoede", gender: "Р¶РµРЅСЃРєРёР№", description: "РњРµР»РѕРґРёС‡РЅС‹Р№, РґСЂР°РјР°С‚РёС‡РµСЃРєРёР№, СЌРїРёС‡РµСЃРєРёР№" },
];

export interface Poster {
  title?: string;
  tagline?: string;
  tags?: string[];
}

export interface BriefOptions {
  length: Record<string, string>;
  pillars: Record<string, string>;
  amounts: Record<string, string>;
  emotions: Record<string, string>;
  threat: Record<string, string>;
  max_emotions: number;
}

export type PersonaSettings = Record<string, string | number>;

export interface CampaignOptions {
  brief: BriefOptions;
  persona: Record<string, Record<string, string>> & { default: PersonaSettings };
  presets: { id: string; name: string; settings: PersonaSettings; style: string }[];
}

export interface Persona {
  id: string;
  name: string;
  settings: PersonaSettings;
  style: string;
}

export interface MasterCharacterSheet {
  text: string;
  fields: Record<string, string>;
  core: string[];
}

export interface MasterPreset {
  id: string;
  name: string;
  model_profile_id: string | null;
  model_profile_name: string | null;
  model_resolved: string | null;
  provider: string | null;
  persona_id: string | null;
  persona_preset: string | null;
  persona_settings: PersonaSettings | null;
  style: string | null;
  style_preview: string | null;
  character: MasterCharacterSheet | null;
  updated_at: string | null;
}

export interface ModelCheck {
  at?: string;
  ok?: boolean;
  latency_ms?: number;
  reply?: string;
  error?: string;
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: "claude" | "gemini" | "local";
  model: string;
  resolved_model: string | null;
  api_base: string | null;
  temperature: number;
  is_default: boolean;
  last_check: ModelCheck;
  campaigns: number;
}

export interface Provider {
  id: string;
  title: string;
  key_env: string | null;
  key_set: boolean | null;
  main_model: string | null;
  technical_model: string | null;
  api_base: string | null;
  is_active: boolean;
}

export interface Pack {
  id: string;
  version: string;
  name: string;
  counts?: Record<string, number>;
  imported_at?: string;
}

export const PROVIDER_RU: Record<string, string> = { claude: "Claude", gemini: "Gemini", local: "LM Studio" };
export const ROLE_RU: Record<string, string> = { super_admin: "РЎСѓРїРµСЂР°РґРјРёРЅ", admin: "РђРґРјРёРЅ", player: "РРіСЂРѕРє" };
export const DIFFICULTY_RU: Record<string, string> = {
  easy: "Р›С‘РіРєР°СЏ",
  normal: "РћР±С‹С‡РЅР°СЏ",
  hard: "РЎР»РѕР¶РЅР°СЏ",
  deadly: "РЎРјРµСЂС‚РµР»СЊРЅР°СЏ",
};

export const LEVELING_RU: Record<string, string> = {
  xp: "РџРѕ РѕРїС‹С‚Сѓ",
  milestone: "РџРѕ РІРµС…Р°Рј СЃСЋР¶РµС‚Р°",
};
export const LEVELING_HINT: Record<string, string> = {
  xp: "РћРїС‹С‚ Р·Р° РїРѕР±РµР¶РґС‘РЅРЅС‹С… РІСЂР°РіРѕРІ, Р·Р°РґР°С‡Рё Рё РєРІРµСЃС‚С‹ РґРµР»РёС‚СЃСЏ РїРѕСЂРѕРІРЅСѓ РјРµР¶РґСѓ РіРµСЂРѕСЏРјРё; СѓСЂРѕРІРµРЅСЊ СЂР°СЃС‚С‘С‚ СЃР°Рј РїРѕ С‚Р°Р±Р»РёС†Рµ SRD.",
  milestone: "РћРїС‹С‚ РЅРµ РєРѕРїРёС‚СЃСЏ: РјР°СЃС‚РµСЂ РїРѕРґРЅРёРјР°РµС‚ СѓСЂРѕРІРµРЅСЊ РІСЃРµРјСѓ РѕС‚СЂСЏРґСѓ РЅР° РІРµС…Р°С… СЃСЋР¶РµС‚Р°.",
};

/** Р’С‹Р±РѕСЂ РїРµСЂСЃРѕРЅС‹ РІ РѕРґРЅРѕРј РїРѕР»Рµ: СЃРІРѕСЏ РёР· РїСЂРѕС„РёР»СЏ, РІСЃС‚СЂРѕРµРЅРЅР°СЏ РёР»Рё РЅРёРєР°РєРѕР№. */
export type PersonaPick = "" | `my:${string}` | `pre:${string}`;

export function personaBody(pick: PersonaPick): { persona_id?: string; preset?: string } {
  if (pick.startsWith("my:")) return { persona_id: pick.slice(3) };
  if (pick.startsWith("pre:")) return { preset: pick.slice(4) };
  return {};
}

// --- С‡РµСЂРЅРѕРІРёРє РЅРѕРІРѕР№ РєР°РјРїР°РЅРёРё: Р¶РёРІС‘С‚ РІ Р±СЂР°СѓР·РµСЂРµ, РїРѕРєР° РєР°РјРїР°РЅРёСЏ РЅРµ СЃРѕР·РґР°РЅР° ---

export interface CampaignDraft {
  step: number;
  name: string;
  pack_id: string;
  difficulty: string;
  /** Р РѕСЃС‚ СѓСЂРѕРІРЅРµР№: РїРѕ РѕРїС‹С‚Сѓ SRD РёР»Рё РїРѕ РІРµС…Р°Рј СЃСЋР¶РµС‚Р°. */
  leveling: "xp" | "milestone";
  players: number | null;
  /** "owner" вЂ” РІРµРґС‘С‚ СЃР°Рј, РёРЅР°С‡Рµ id РїСЂРѕС„РёР»СЏ РјРѕРґРµР»Рё ("" вЂ” РјРѕРґРµР»СЊ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ). */
  master: string;
  persona: PersonaPick;
  master_preset_id: string | null;
  master_character: MasterCharacterSheet | null;
  master_style: string;
  owner_plays: boolean;
  review: "master" | "auto";
  brief: Brief;
  excluded: string;
  public_intro: string;
  plan_now: boolean;
}

export const EMPTY_DRAFT: CampaignDraft = {
  step: 0,
  name: "",
  pack_id: "",
  difficulty: "normal",
  leveling: "xp",
  players: null,
  master: "",
  persona: "pre:storyteller",
  master_preset_id: null,
  master_character: null,
  master_style: "",
  owner_plays: true,
  review: "master",
  brief: {},
  excluded: "",
  public_intro: "",
  plan_now: true,
};

export const WIZARD_STEPS = ["РњРёСЂ", "РњР°СЃС‚РµСЂ", "Р§РµРіРѕ Р¶РґС‘С‚Рµ", "Р’РІРѕРґРЅР°СЏ"] as const;

const DRAFT_KEY = "tf-campaign-draft";

export function loadDraft(userId: string): CampaignDraft | null {
  try {
    const raw = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null");
    if (!raw || raw.user !== userId) return null;
    return { ...EMPTY_DRAFT, ...raw.draft };
  } catch {
    return null;
  }
}

export function saveDraft(userId: string, draft: CampaignDraft | null): void {
  try {
    if (draft) localStorage.setItem(DRAFT_KEY, JSON.stringify({ user: userId, draft }));
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* РїСЂРёРІР°С‚РЅС‹Р№ СЂРµР¶РёРј: С‡РµСЂРЅРѕРІРёРє Р¶РёРІС‘С‚, РїРѕРєР° РѕС‚РєСЂС‹С‚Р° РІРєР»Р°РґРєР° */
  }
}

export function splitThemes(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 20);
}

/** РђРЅРєРµС‚Р° Р±РµР· РїСѓСЃС‚С‹С… РїРѕР»РµР№: С‡РµРіРѕ РЅРµ РІС‹Р±СЂР°Р»Рё, СЂРµС€Р°РµС‚ РјР°СЃС‚РµСЂ. РЎСЂРµРґРЅРёРµ РґРѕР»Рё РЅРµ С€Р»С‘Рј вЂ” СЌС‚Рѕ Рё С‚Р°Рє РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ. */
export function cleanBrief(b: Brief): Brief {
  const out: Brief = {};
  if (b.length) out.length = b.length;
  if (b.threat) out.threat = b.threat;
  const pillars = Object.fromEntries(Object.entries(b.pillars ?? {}).filter(([, v]) => v && v !== "mid"));
  if (Object.keys(pillars).length) out.pillars = pillars;
  if (b.emotions?.length) out.emotions = b.emotions;
  if (b.wishes?.trim()) out.wishes = b.wishes.trim();
  return out;
}

export function createBody(d: CampaignDraft): Record<string, unknown> {
  const owner = d.master === "owner";
  const persona = personaBody(d.persona);
  const master = owner
    ? { type: "owner" }
    : {
        type: "agent",
        ...(d.master ? { model_profile_id: d.master } : {}),
        ...(persona.preset ? { persona_preset: persona.preset } : {}),
        ...(persona.persona_id ? { persona_id: persona.persona_id } : {}),
        ...(d.master_style ? { style: d.master_style } : {}),
        ...(d.master_character ? { character: d.master_character } : {}),
        ...(d.master_preset_id ? { preset_id: d.master_preset_id } : {}),
      };
  return {
    name: d.name.trim(),
    pack_id: d.pack_id || null,
    difficulty: d.difficulty,
    leveling: d.leveling,
    ...(d.players ? { players: d.players } : {}),
    master,
    public_intro: d.public_intro,
    brief: cleanBrief(d.brief),
    excluded_themes: splitThemes(d.excluded),
    creation_rules: { review: d.review },
    owner_plays: !owner && d.owner_plays,
  };
}

/** Р§С‚Рѕ РјРµС€Р°РµС‚ РїРµСЂРµР№С‚Рё РґР°Р»СЊС€Рµ СЃ С€Р°РіР°: РїСѓСЃС‚РѕР№ СЃРїРёСЃРѕРє вЂ” РјРѕР¶РЅРѕ. */
export function stepProblems(d: CampaignDraft, step: number): string[] {
  if (step === 0 && !d.name.trim()) return ["РќР°Р·РѕРІРёС‚Рµ РєР°РјРїР°РЅРёСЋ"];
  return [];
}

