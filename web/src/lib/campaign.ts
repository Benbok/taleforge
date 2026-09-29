// Кампания вне игры: создание по шагам, кабинет владельца, настройки мастера. Подписи вариантов приходят
// с сервера (/api/campaign-options), здесь только типы и то, что собирает запросы.

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

/** Кампания, как её видит участник (GET /api/campaigns/{id}). brief — только владельцу и мастеру. */
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
    poster?: Poster | null;
    [k: string]: unknown;
  };
  brief: Brief | null;
  seats: Seat[];
}

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
  default_model: string | null;
  api_base: string | null;
}

export interface Pack {
  id: string;
  version: string;
  name: string;
  counts?: Record<string, number>;
  imported_at?: string;
}

export const PROVIDER_RU: Record<string, string> = { claude: "Claude", gemini: "Gemini", local: "LM Studio" };
export const ROLE_RU: Record<string, string> = { super_admin: "Суперадмин", admin: "Админ", player: "Игрок" };
export const DIFFICULTY_RU: Record<string, string> = {
  easy: "Лёгкая",
  normal: "Обычная",
  hard: "Сложная",
  deadly: "Смертельная",
};

/** Выбор персоны в одном поле: своя из профиля, встроенная или никакой. */
export type PersonaPick = "" | `my:${string}` | `pre:${string}`;

export function personaBody(pick: PersonaPick): { persona_id?: string; preset?: string } {
  if (pick.startsWith("my:")) return { persona_id: pick.slice(3) };
  if (pick.startsWith("pre:")) return { preset: pick.slice(4) };
  return {};
}

// --- черновик новой кампании: живёт в браузере, пока кампания не создана ---

export interface CampaignDraft {
  step: number;
  name: string;
  pack_id: string;
  difficulty: string;
  players: number | null;
  /** "owner" — ведёт сам, иначе id профиля модели ("" — модель по умолчанию). */
  master: string;
  persona: PersonaPick;
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
  players: null,
  master: "",
  persona: "pre:storyteller",
  owner_plays: true,
  review: "master",
  brief: {},
  excluded: "",
  public_intro: "",
  plan_now: true,
};

export const WIZARD_STEPS = ["Мир", "Мастер", "Чего ждёте", "Вводная"] as const;

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
    /* приватный режим: черновик живёт, пока открыта вкладка */
  }
}

export function splitThemes(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 20);
}

/** Анкета без пустых полей: чего не выбрали, решает мастер. Средние доли не шлём — это и так по умолчанию. */
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
      };
  return {
    name: d.name.trim(),
    pack_id: d.pack_id || null,
    difficulty: d.difficulty,
    ...(d.players ? { players: d.players } : {}),
    master,
    public_intro: d.public_intro,
    brief: cleanBrief(d.brief),
    excluded_themes: splitThemes(d.excluded),
    creation_rules: { review: d.review },
    owner_plays: !owner && d.owner_plays,
  };
}

/** Что мешает перейти дальше с шага: пустой список — можно. */
export function stepProblems(d: CampaignDraft, step: number): string[] {
  if (step === 0 && !d.name.trim()) return ["Назовите кампанию"];
  return [];
}
