// Формы данных сервера, которые читает клиент. Неизвестные поля клиент игнорирует.

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

export interface ChatMessage {
  id: string;
  seq: number;
  kind: string;
  seat_id: string | null;
  author: string | null;
  content: string;
  whisper: boolean;
  data?: RollCard | null;
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
}

export interface Scene {
  mode: "free" | "combat";
  round: number;
  location: { id: string; name: string } | null;
  entities: SceneEntity[];
  turn: Turn | null;
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
  public_bio?: string;
}

export type EntityType = "creature" | "npc" | "item" | "location" | "lore" | "hero";

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
  error?: string;
}

export interface SeatState {
  id: string;
  role: "master" | "player";
  position: number;
  occupant_type: "human" | "agent" | "empty";
  user_name: string | null;
  presence: "online" | "offline" | null;
}

export interface Snapshot {
  protocol: number;
  campaign: { id: string; name: string; status: CampaignStatus; public_intro: string };
  session: { id: string; started_at: string } | null;
  me: { user_id: string; seat_id: string | null; role: string | null; is_owner: boolean };
  seats: SeatState[];
  turn: Turn | null;
  heroes: HeroPublic[];
  scene: Scene;
  actions: string[];
  blocked: Record<string, string>;
  pending: PendingReply | null;
  collect_window_sec: number;
  messages: ChatMessage[];
  replay: boolean;
}
