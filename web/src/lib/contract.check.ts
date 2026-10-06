// Проверка на этапе сборки: ответы сервера подходят под типы, которыми их читает клиент. Формы ответов — из
// контракта сервера (lib/api.gen.ts); если сервер переименует или уберёт поле, которое ждёт клиент, `tsc` упадёт
// на строке нужного маршрута. Новый тип ответа в клиенте — новая строка здесь.
import type { paths } from "./api.gen";
import type { CampaignHero } from "./builder";
import type { Room } from "./campaign";
import type { CampaignCard, HeroSheet, InvitePreview, User } from "./types";

type Json<R> = R extends { content: { "application/json": infer T } } ? T : never;
/** Тело успешного ответа маршрута ``P`` на метод ``M``. */
export type Res<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  responses: infer R;
}
  ? R extends { 200: infer A }
    ? Json<A>
    : R extends { 201: infer B }
      ? Json<B>
      : never
  : never;

// Каждая строка: «ответ маршрута можно положить в тип клиента». Файл не входит в сборку, его читает только tsc.
declare const user: Res<"/api/auth/me", "get">;
export const userFits: User = user;
declare const cards: Res<"/api/me/campaigns", "get">;
export const cardsFits: CampaignCard[] = cards;
declare const invite: Res<"/api/invites/{token}", "get">;
export const inviteFits: InvitePreview = invite;
declare const created: Res<"/api/campaigns", "post">;
export const createdFits: Room = created;
declare const room: Res<"/api/campaigns/{campaign_id}", "get">;
export const roomFits: Room = room;
declare const taken: Res<"/api/campaigns/{campaign_id}/seats/take", "post">;
export const takenFits: Room = taken;
declare const heroes: Res<"/api/campaigns/{campaign_id}/characters", "get">;
export const heroesFits: CampaignHero[] = heroes;
declare const hero: Res<"/api/campaigns/{campaign_id}/characters/{character_id}", "get">;
export const heroFits: CampaignHero = hero;
declare const sheet: Res<"/api/campaigns/{campaign_id}/characters/{character_id}", "get">;
// книгу заклинаний сервер пока не описывает (views.py, SheetParts.spellbook): её форма — в lib/spells.ts
export const sheetFits: Partial<Omit<HeroSheet, "spellbook">> = sheet;
