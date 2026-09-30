// Формы данных сервера, которые читает клиент. Неизвестные поля клиент игнорирует.
import type { Spellbook } from "./spells";

export interface User {
  id: string;
  name: string;
  platform_role: "super_admin" | "admin" | "player";
}

export interface PartyMember {
  seat_id: string;
  role: "master" | "player";
  occupant_type: "human" | "agent" | "empty";
  user_name: string | null;
  hero_name: string | null;
  online: boolean;
}

export type CampaignStatus = "lobby" | "active" | "paused" | "ended";

export interface CampaignCard {
  id: string;
  name: string;
  world: string | null;
  status: CampaignStatus;
  session_live: boolean;
  waiting_players: number;
  my_role: "master" | "player" | null;
  is_owner: boolean;
  hero: { id: string; name: string; status: string; level: number | null } | null;
  party: PartyMember[];
  recap: string | null;
  last_session_at: string | null;
  created_at: string;
}

export interface InvitePreview {
  campaign_name: string;
  public_intro: string;
  free_seats: number;
  valid: boolean;
  problem: string | null;
  pack_id?: string | null;
}

export type Palette = Record<string, string>;

export interface Theme {
  dark: Palette;
  light: Palette;
  fonts: { narration: string; ui: string; heading: string };
  font_css: string | null;
  labels: Record<string, string>;
}

export interface Envelope<P = Record<string, unknown>> {
  type: string;
  campaign_id: string | null;
  seq: number | null;
  payload: P;
}

/** Статус реплики игрока при ИИ-мастере: ждёт хода, мастер отвечает, отвечено, не обработано. */
export type ReplyState = "pending" | "processing" | "answered" | "failed";

/** Своя реплика, ждущая хода мастера: её можно отменить. */
export interface PendingReply {
  id: string;
  created_at: string | null;
}

/** Голосовая запись реплики (этап голосового ввода). */
export interface VoiceData {
  id: string;
  mime: string;
  duration: number | null;
}

export interface ChatMessage {
  id: string;
  seq: number;
  kind: string;
  seat_id: string | null;
  author: string | null;
  content: string;
  whisper: boolean;
  // у реплики ИИ-игрока — { ai: true }; у голосовой — { voice }: запись автора, content — её расшифровка
  data?: (RollCard & { ai?: boolean; voice?: VoiceData }) | null;
  created_at: string | null;
  state?: ReplyState | null;
}

export interface RollCard {
  tool: string;
  title: string;
  who?: string | null;
  target?: string | null;
  reason?: string | null;
  roll?: { d20?: number[]; natural?: number; modifier?: number; mode?: string | null; total?: number } | null;
  against?: { label: string; value: number } | null;
  outcome: "success" | "fail" | "hit" | "miss" | "crit" | "info";
  damage?: { amount: number; type: string; dice: { expr: string; total: number }[] };
  dice?: { expr: string; total: number }[];
  order?: { id: string; name: string | null; initiative: number }[];
  track?: { successes: number; failures: number };
  notes?: string[];
}

export interface Turn {
  round: number;
  actor_id: string;
  name: string;
  seat_id: string | null;
  deadline: number | null;
  submitted: boolean;
}

export interface SceneEntity {
  id: string;
  name: string;
  kind: string;
  zone: string;
  condition?: string;
  attitude?: string;
  /** Предмет, лежащий в сцене: его можно подобрать. */
  item?: boolean;
  qty?: number;
}

/** Участник полосы инициативы. Числа существ сервер не присылает. */
export interface OrderEntry {
  id: string;
  name: string;
  initiative: number | null;
  side: "hero" | "enemy" | "ally";
  seat_id?: string | null;
  out: string | null;
}

export interface Scene {
  mode: "free" | "combat";
  round: number;
  location: { id: string; name: string } | null;
  entities: SceneEntity[];
  order?: OrderEntry[];
  turn: Turn | null;
}

/** Кнопка реакции (атака по возможности): висит, пока не выбрано или не вышло время. */
export interface ReactionPrompt {
  prompt_id: string;
  character_id: string;
  trigger: string;
  options: { id: string; label: string }[];
  expires_at: number;
}

/** Итог сессии: сводка строится только из публичных сообщений. */
export interface SessionSummary {
  recap: string;
  events: string[];
  quests: string[];
}

export interface HeroPublic {
  id: string;
  name: string;
  seat_id: string | null;
  status: string;
  level: number;
  hp: number | null;
  hp_max: number | null;
  dead: boolean;
  /** Спасброски от смерти [успехи, провалы], пока герой без сознания; бросаются открыто. */
  death_saves?: [number, number] | null;
  public_bio?: string;
  class_name?: string | null;
  origin_name?: string | null;
  bonds?: { question: string; answer: string }[];
}

export type EntityType = "creature" | "npc" | "item" | "location" | "landmark" | "lore" | "hero";

export interface EntityCard {
  id: string;
  type?: EntityType;
  name?: string;
  level?: number | null;
  level_name?: string;
  description?: string | null;
  locked?: string[];
  kind_name?: string;
  lore?: string;
  habits?: string;
  condition?: string | null;
  attacks?: string[];
  vulnerable?: string[];
  stats?: Record<string, unknown>;
  hero?: HeroPublic;
  facts?: string[];
  heard?: string[];
  error?: string;
}

export interface HeroAttack {
  key: string;
  name: string;
  attack_bonus: number;
  damage: string;
  damage_type: string;
  kind: "melee" | "ranged";
  inventory_id?: string | null;
}

/** Полный лист своего героя (сервер отдаёт его только игроку этого героя и мастеру). */
export interface HeroSheet extends HeroPublic {
  class_name?: string | null;
  origin_name?: string | null;
  /** Вторая раса после Порога и её каста. */
  lineage?: { id: string; name: string; caste: string | null; features: string[] } | null;
  sheet: Record<string, unknown> & { level?: number; skills?: string[] };
  resources: {
    hp?: number;
    hp_max?: number;
    temp_hp?: number;
    hit_dice?: number;
    death_saves?: [number, number];
    dead?: boolean;
    /** Вдохновение SRD: награда мастера, тратится на преимущество в одном броске. */
    inspiration?: boolean;
  };
  private_backstory?: string | null;
  /** Анкета характера {text, fields, core}; у старых героев — плоский словарь «поле: текст». */
  personality?: Record<string, unknown> | null;
  derived?: {
    abilities: Record<string, number>;
    mods: Record<string, number>;
    ac: number;
    hp_max: number;
    saves: Record<string, number>;
    skills: Record<string, number>;
    pb: number;
    speed?: number;
    attacks: HeroAttack[];
    effects: { id: string; template: string; name: string; stacks: number }[];
  };
  inventory: { id: string; item: string; name: string; qty: number; equipped: boolean }[];
  /** Опыт: сколько есть, порог текущего уровня и следующего (null — выше расти некуда). */
  progress?: { xp: number; level_xp: number; next_xp: number | null };
  /** Книга заклинаний: у заклинателей. */
  spellbook?: Spellbook | null;
}

export interface Explained {
  stat: string;
  character_id: string;
  label?: string;
  value?: number | string | null;
  parts?: { label: string; value: string }[];
  note?: string | null;
  history?: string[];
  error?: string;
}

export interface SeatState {
  id: string;
  role: "master" | "player";
  position: number;
  occupant_type: "human" | "agent" | "empty";
  user_name: string | null;
  /** «Переподключается» — первые 60 секунд после обрыва во время сессии, потом «офлайн» и голосование. */
  presence: Presence;
  /** Кто ведёт место, пока его хозяин вне сети: другой игрок или ИИ-мастер. */
  stand_in?: StandIn | null;
}

export type Presence = "online" | "reconnecting" | "offline" | null;

export interface StandIn {
  user_id?: string;
  name: string;
  ai?: boolean;
}

/** Голосование, когда игрок или живой мастер ушёл из сети (ТЗ, раздел 11). */
export interface Vote {
  vote_id: string;
  seat_id: string;
  subject: "player" | "master";
  who: string;
  hero: string | null;
  options: { id: string; label: string }[];
  voters: string[];
  voted: string[];
  tally: Record<string, number>;
  deadline: number;
}

/** Дорожка, которая звучит в слое (design/audio-mixer.md). */
export interface AudioTrack {
  id: string;
  title: string;
  layer: string;
  url: string;
  bpm: number | null;
  bars: number | null;
  gain_db: number;
  level?: number; // громкость слоя от мастера, 0..1
  since?: number; // с какого момента по часам сервера звучит петля
}

export type LoopLayer = "music" | "rhythm" | "ambience";

export interface AudioState {
  enabled: boolean;
  v: number;
  now: number; // часы сервера в момент отправки
  layers: Record<LoopLayer, AudioTrack | null>;
  cues?: AudioTrack[]; // эффекты: звучат один раз с этим событием
}

export interface Snapshot {
  protocol: number;
  campaign: { id: string; name: string; status: CampaignStatus; public_intro: string };
  session: { id: string; started_at: string } | null;
  me: { user_id: string; seat_id: string | null; role: string | null; is_owner: boolean; stand_in_for?: string[] };
  seats: SeatState[];
  votes?: Vote[];
  turn: Turn | null;
  reaction?: ReactionPrompt | null;
  summary?: SessionSummary | null;
  heroes: HeroPublic[];
  scene: Scene;
  audio?: AudioState;
  actions: string[];
  blocked: Record<string, string>;
  pending: PendingReply | null;
  collect_window_sec: number;
  messages: ChatMessage[];
  replay: boolean;
}
