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

export interface ChatMessage {
  id: string;
  seq: number;
  kind: string;
  seat_id: string | null;
  author: string | null;
  content: string;
  whisper: boolean;
  created_at: string | null;
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
  turn: Record<string, unknown> | null;
  messages: ChatMessage[];
  replay: boolean;
}
