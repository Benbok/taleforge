export interface SavedHero {
  id: string;
  name: string;
  status?: string;
  sheet?: Record<string, unknown> | null;
  public_bio?: string | null;
  private_backstory?: string | null;
  errors?: string[];
}

export interface CampaignHero extends SavedHero {
  combat?: { inventory: { id: string; kind: string; name: string; description?: string }[] } | null;
  seat_id: string | null;
  status: string;
  reviewer?: "ai" | "master" | null;
  review_error?: string | null;
  review_status?: "queued" | "running" | "failed" | "interrupted";
  review_attempt_id?: string | null;
  review_comment?: string | null;
  derived?: { hp_max?: number; ac?: number } | null;
}

/** Герой из профиля игрока. */
export interface LibraryHero extends SavedHero {
  portrait_url?: string | null;
  /** Мир, для которого собран герой: null — авторский мир. */
  pack_id: string | null;
  world_name: string | null;
  level: number;
  errors: string[];
  copies?: { campaign_id: string; campaign_name: string; character_id: string; status: string; level: number }[];
}

