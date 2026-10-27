import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import Avatar from "../components/Avatar";
import PersonaEditor from "../components/PersonaEditor";
import { api } from "../lib/api";
import type { CampaignHero } from "../lib/builder";
import type { Room, Seat } from "../lib/campaign";
import { toast } from "../stores/toasts";

interface Invite {
  token: string;
  url: string;
  expires_at: string | null;
  max_uses: number | null;
  uses: number;
  revoked: boolean;
}

interface Reviewable extends CampaignHero {
  derived?: { hp_max?: number; ac?: number; abilities?: Record<string, number> } | null;
}

const DATE = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

/** Игроки: места за столом, приглашения, герои на проверке и готовые герои для игроков. */
export default function PlayersTab({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  const id = room.id;
  const qc = useQueryClient();
  const chars = useQuery({
    queryKey: ["characters", id],
    queryFn: () => api<Reviewable[]>(`/api/campaigns/${id}/characters`),
    refetchInterval: 10000,
  });
  const invites = useQuery({
    queryKey: ["invites", id],
    queryFn: () => api<Invite[]>(`/api/campaigns/${id}/invites`),
    enabled: room.is_owner,
  });
  const [character, setCharacter] = useState<string | null>(null); // место ИИ-игрока, чей характер открыт

  const players = room.seats.filter((s) => s.role === "player").sort((a, b) => a.position - b.position);
  const totalSeats = players.length;
  const freeSeats = players.filter((s) => s.occupant_type === "empty").length;
  const heroesInGame = (chars.data ?? []).filter((c) => ["approved", "active"].includes(c.status)).length;

  const heroOf = (seatId: string) =>
    (chars.data ?? []).find((c) => c.seat_id === seatId && !["dead", "retired", "premade"].includes(c.status));
  const now = Date.now();
  const live = (invites.data ?? []).filter(
    (i) => !i.revoked && (!i.expires_at || Date.parse(i.expires_at) > now) && (i.max_uses == null || i.uses < i.max_uses),
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Seats at the table */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <div>
            <h2 className="font-heading text-xl font-bold text-ink">Состав отряда за столом</h2>
            <p className="text-xs text-muted">Участники, закреплённые места и привязанные герои</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {room.is_owner && room.status !== "ended" && (
              <ActionButton
                className="font-mono text-xs"
                disabled={totalSeats >= 6}
                title={totalSeats >= 6 ? "Достигнут максимум мест (6)" : undefined}
                run={async () => {
                  const updated = await api<Room>(`/api/campaigns/${id}/seats`, { method: "POST" });
                  onRoom(updated);
                }}
                done="Место игрока добавлено"
              >
                + ДОБАВИТЬ МЕСТО ИГРОКА
              </ActionButton>
            )}
            {room.is_owner && !room.my_seat_id && (
              <ActionButton
                className="font-mono text-xs"
                run={async () => onRoom(await api<Room>(`/api/campaigns/${id}/seats/take`, { method: "POST" }))}
                done="Вы заняли место игрока"
              >
                ЗАНЯТЬ МЕСТО ИГРОКА
              </ActionButton>
            )}
          </div>
        </div>

        <div className="rounded border border-line bg-surface-alt/40 px-3 py-2 text-xs flex flex-wrap items-center justify-between gap-2">
          <div className="font-mono text-ink">
            Мест: {totalSeats} из 6 · Свободно: {freeSeats} · Героев в игре: {heroesInGame}
          </div>
          <div className="text-[11px] text-muted">
            {room.status === "lobby" && "Вступление героев открыто (до старта сессии)"}
            {room.status === "paused" && "Вступление героев доступно на паузе (вне боя и ходов мастера)"}
            {room.status === "active" && "Идёт сессия: новые герои могут вступить на паузе"}
            {room.status === "ended" && "Кампания завершена"}
          </div>
        </div>
        <p className="text-xs text-muted">
          Новый герой вступает в текущую локацию сцены. Если отряд разделён, герой присоединится к группе в этой локации.
        </p>

        <div className="divide-y divide-line/60">
          {players.map((s) => {
            const h = heroOf(s.id);
            const isMe = s.id === room.my_seat_id;
            const isEmpty = s.occupant_type === "empty";
            return (
              <div key={s.id} className="py-3 first:pt-1 last:pb-1">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Avatar name={h?.name ?? s.user_name} role={s.role} occupant={s.occupant_type} presence={null} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink">
                        {isEmpty ? "Свободное место" : s.occupant_type === "agent" ? "ИИ-игрок" : s.user_name}
                      </span>
                      {isMe && (
                        <span className="rounded bg-raised px-1.5 py-0.2 font-mono text-[10px] text-accent font-semibold border border-line">
                          ВЫ
                        </span>
                      )}
                    </div>
                    {!isEmpty && (
                      <div className="font-mono text-xs text-muted mt-0.5">
                        {h ? (
                          <span>
                            <span className="text-accent font-medium">{h.name}</span> · {heroState(h.status)}
                          </span>
                        ) : (
                          <span className="text-faint">персонаж ещё не выбран</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {room.is_owner && s.occupant_type === "human" && !isMe && (
                  <ActionButton
                    danger
                    className="px-2.5 py-1 text-xs font-mono self-start sm:self-center"
                    confirm={`Освободить место игрока ${s.user_name}? Его герой останется в кампании.`}
                    run={async () =>
                      onRoom(await api<Room>(`/api/campaigns/${id}/seats/${s.id}/occupant`, { method: "DELETE" }))
                    }
                    done="Место освобождено"
                  >
                    Освободить место
                  </ActionButton>
                )}
                {room.is_owner && s.occupant_type === "empty" && <SeatAi campaignId={id} seat={s} onRoom={onRoom} />}
                {room.is_owner && s.occupant_type === "agent" && (
                  <span className="flex gap-1.5 self-start sm:self-center">
                    {h && h.status !== "draft" && (
                      <button
                        className="btn px-2.5 py-1 font-mono text-xs"
                        onClick={() => setCharacter(character === s.id ? null : s.id)}
                      >
                        {character === s.id ? "Свернуть" : "Характер"}
                      </button>
                    )}
                    <ActionButton
                      danger
                      className="px-2.5 py-1 font-mono text-xs"
                      confirm="Убрать ИИ-игрока? Его герой останется за местом: его получит тот, кто сядет."
                      run={async () => {
                        onRoom(await api<Room>(`/api/campaigns/${id}/seats/${s.id}/occupant`, { method: "DELETE" }));
                      }}
                      done="ИИ-игрок ушёл, место свободно"
                    >
                      Убрать
                    </ActionButton>
                  </span>
                )}
                </div>
                {character === s.id && h && (
                  <div className="mt-3 rounded-md border border-line p-3">
                    <PersonaEditor base={`/api/campaigns/${id}/characters/${h.id}/persona`} query={`?as_seat=${s.id}`} />
                  </div>
                )}

              </div>
            );
          })}
        </div>
      </section>

      {/* Invites Management */}
      {room.is_owner && (
        <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
            <div>
              <h2 className="font-heading text-xl font-bold text-ink">Ссылки-приглашения</h2>
              <p className="text-xs text-muted">Отправьте ссылку игрокам, чтобы они могли присоединиться к этому столу</p>
            </div>
            <ActionButton
              primary
              className="font-mono text-xs tracking-wider"
              run={async () => {
                const inv = await api<Invite>(`/api/campaigns/${id}/invites`, { body: {} });
                await qc.invalidateQueries({ queryKey: ["invites", id] });
                await copy(inv.url);
              }}
            >
              + СОЗДАТЬ ССЫЛКУ
            </ActionButton>
          </div>

          {invites.isError && (
            <div className="card border-bad/40 bg-bad/5 p-4 text-xs text-bad">
              Не удалось загрузить приглашения: {(invites.error as Error).message}
            </div>
          )}

          {invites.isSuccess && live.length === 0 && (
            <p className="text-xs sm:text-sm text-muted">
              Активных ссылок нет. Каждая созданная ссылка действует 3 дня.
            </p>
          )}

          <div className="flex flex-col gap-2.5">
            {live.map((i) => (
              <div
                key={i.token}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-[8px] border border-line bg-raised/50 p-2.5"
              >
                <input
                  className="field min-w-0 font-mono text-xs py-1 px-2.5 flex-1 select-all"
                  readOnly
                  value={i.url}
                  onFocus={(e) => e.currentTarget.select()}
                  aria-label="Ссылка-приглашение"
                />
                <div className="flex items-center justify-between sm:justify-end gap-2 font-mono text-xs">
                  <span className="text-faint text-[11px]">
                    {i.expires_at ? `до ${DATE.format(new Date(i.expires_at))}` : "бессрочно"}
                    {i.uses ? ` · перешли ${i.uses}` : ""}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      className="btn px-2.5 py-1 text-xs font-mono"
                      onClick={() => void copy(i.url)}
                    >
                      Копировать
                    </button>
                    <ActionButton
                      className="px-2 py-1 text-xs font-mono text-bad hover:border-bad"
                      run={async () => {
                        await api(`/api/campaigns/${id}/invites/${i.token}`, { method: "DELETE" });
                        await qc.invalidateQueries({ queryKey: ["invites", id] });
                      }}
                      done="Ссылка отозвана"
                    >
                      Отозвать
                    </ActionButton>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}


    </div>
  );
}

/** ИИ-игрок на свободное место. */
function SeatAi({ campaignId, seat, onRoom }: { campaignId: string; seat: Seat; onRoom: (r: Room) => void }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <ActionButton
        className="px-2 py-0.5 text-xs"
        run={async () =>
          onRoom(
            await api<Room>(`/api/campaigns/${campaignId}/seats/${seat.id}/agent`, { body: {} }),
          )
        }
        done="ИИ-игрок сел за стол. Соберите ему героя"
      >
        Посадить ИИ-игрока
      </ActionButton>
    </span>
  );
}

function heroState(status: string): string {
  return { draft: "собирает героя", submitted: "на проверке", approved: "готов к игре", active: "в игре" }[status] ?? status;
}

async function copy(url: string) {
  try {
    await navigator.clipboard.writeText(url);
    toast.ok("Ссылка скопирована в буфер обмена");
  } catch {
    toast.info(`Ссылка: ${url}`);
  }
}
