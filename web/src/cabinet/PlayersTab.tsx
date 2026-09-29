import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import Avatar from "../components/Avatar";
import Builder from "../builder/Builder";
import PersonaEditor from "../components/PersonaEditor";
import { ABILITIES, ABILITY_ABBR } from "../game/hero";
import { api } from "../lib/api";
import type { BuilderOptions, CampaignHero } from "../lib/builder";
import type { ModelProfile, Room, Seat } from "../lib/campaign";
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
  const refreshChars = () => qc.invalidateQueries({ queryKey: ["characters", id] });
  const [building, setBuilding] = useState<string | null>(null); // место ИИ-игрока, чьего героя собирает владелец
  const [character, setCharacter] = useState<string | null>(null); // место ИИ-игрока, чей характер открыт

  const players = room.seats.filter((s) => s.role === "player").sort((a, b) => a.position - b.position);
  const heroOf = (seatId: string) =>
    (chars.data ?? []).find((c) => c.seat_id === seatId && !["dead", "retired", "premade"].includes(c.status));
  const waiting = (chars.data ?? []).filter((c) => c.status === "submitted" && c.seat_id !== room.my_seat_id);
  const premades = (chars.data ?? []).filter((c) => c.status === "premade");
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
        {room.is_owner && players.some((s) => s.occupant_type !== "human") && <RolesHint campaignId={id} />}

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
                    {(!h || h.status === "draft") && (
                      <button className="btn px-2.5 py-1 font-mono text-xs" onClick={() => setBuilding(building === s.id ? null : s.id)}>
                        {building === s.id ? "Свернуть" : h ? "Продолжить героя" : "Собрать героя"}
                      </button>
                    )}
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
                        setBuilding(null);
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
                {building === s.id && (
                  <AiHero
                    campaignId={id}
                    seatId={s.id}
                    hero={h ?? null}
                    onDone={async () => {
                      setBuilding(null);
                      await refreshChars();
                    }}
                    onSaved={() => void refreshChars()}
                  />
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

      {/* Waiting for review heroes */}
      {waiting.length > 0 && (
        <section className="flex flex-col gap-3">
          <div>
            <h2 className="font-heading text-xl font-bold text-ink">Герои на проверке</h2>
            <p className="text-xs text-muted">Листы персонажей, ожидающие решения мастера стола</p>
          </div>
          <div className="grid gap-4">
            {waiting.map((c) => (
              <ReviewCard key={c.id} campaignId={id} hero={c} onDone={refreshChars} />
            ))}
          </div>
        </section>
      )}

      {/* Premade heroes */}
      {room.is_owner && <Premades campaignId={id} premades={premades} onChange={refreshChars} />}
    </div>
  );
}

/** ИИ-игрок на свободное место: модель — профиль из админки или профиль по умолчанию. */
function SeatAi({ campaignId, seat, onRoom }: { campaignId: string; seat: Seat; onRoom: (r: Room) => void }) {
  const [profile, setProfile] = useState("");
  const models = useQuery({
    queryKey: ["models"],
    queryFn: () => api<ModelProfile[]>("/api/admin/models"),
    retry: false,
  });
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {!!models.data?.length && (
        <select className="field py-0.5 text-xs" value={profile} onChange={(e) => setProfile(e.target.value)} aria-label="Модель ИИ-игрока">
          <option value="">Модель по умолчанию</option>
          {models.data.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      )}
      <ActionButton
        className="px-2 py-0.5 text-xs"
        run={async () =>
          onRoom(
            await api<Room>(`/api/campaigns/${campaignId}/seats/${seat.id}/agent`, { body: { model_profile_id: profile || null } }),
          )
        }
        done="ИИ-игрок сел за стол. Соберите ему героя"
      >
        Посадить ИИ-игрока
      </ActionButton>
    </span>
  );
}

interface PartyRoles {
  have: { role: string; label: string; heroes: string[] }[];
  missing: { role: string; label: string; classes: { id: string; name: string }[] }[];
  heroes: number;
  recommended: number;
}

/** Подсказка перед тем, как сажать ИИ-игрока: каких ролей отряду не хватает и какие классы их закроют. */
function RolesHint({ campaignId }: { campaignId: string }) {
  const roles = useQuery({
    queryKey: ["party-roles", campaignId],
    queryFn: () => api<PartyRoles>(`/api/campaigns/${campaignId}/party-roles`),
    refetchInterval: 10000,
  });
  const r = roles.data;
  if (roles.isError) return <p className="text-sm text-bad">Подсказка по ролям не загрузилась: {(roles.error as Error).message}</p>;
  if (!r) return null;
  return (
    <div className="mb-2 rounded-md border border-line p-3 text-sm">
      <p className="text-muted">
        Героев в отряде: {r.heroes} из {r.recommended} рекомендованных.
        {r.have.length > 0 && ` Уже есть: ${r.have.map((h) => h.label).join(", ")}.`}
      </p>
      {r.missing.length > 0 ? (
        <ul className="mt-1 flex flex-col gap-0.5">
          {r.missing.map((m) => (
            <li key={m.role}>
              Не хватает: <span className="font-semibold">{m.label}</span>
              {m.classes.length > 0 && <span className="text-muted"> — {m.classes.map((c) => c.name).join(", ")}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1">Все роли в отряде закрыты.</p>
      )}
    </div>
  );
}

/** Героя ИИ-игрока собирает владелец: тот же конструктор, та же проверка правил и мастера. */
function AiHero({
  campaignId,
  seatId,
  hero,
  onSaved,
  onDone,
}: {
  campaignId: string;
  seatId: string;
  hero: Reviewable | null;
  onSaved: () => void;
  onDone: () => Promise<unknown>;
}) {
  const opts = useQuery({
    queryKey: ["options", campaignId, seatId],
    queryFn: () => api<BuilderOptions>(`/api/campaigns/${campaignId}/character-options?as_seat=${seatId}`),
  });
  return (
    <div className="mt-3">
      {opts.isError && <p className="text-bad">Не удалось загрузить варианты: {(opts.error as Error).message}</p>}
      {opts.data && (
        <Builder
          mode="campaign"
          campaignId={campaignId}
          asSeat={seatId}
          opts={opts.data}
          hero={hero}
          onSaved={onSaved}
          onSubmitted={(status) => {
            toast.ok(status === "approved" ? "Герой ИИ-игрока в игре" : "Герой ИИ-игрока ушёл на проверку");
            void onDone();
          }}
        />
      )}
    </div>
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

/** Герой на проверке: лист, история и тайная предыстория (её видит только проверяющий). */
function ReviewCard({
  campaignId,
  hero,
  onDone,
}: {
  campaignId: string;
  hero: Reviewable;
  onDone: () => Promise<unknown>;
}) {
  const [comment, setComment] = useState("");
  const full = useQuery({
    queryKey: ["character", campaignId, hero.id],
    queryFn: () => api<Reviewable>(`/api/campaigns/${campaignId}/characters/${hero.id}`),
  });
  const h = full.data ?? hero;
  const review = (approve: boolean) => async () => {
    if (!approve && !comment.trim()) throw new Error("Укажите игроку, что именно нужно доработать");
    await api(`/api/campaigns/${campaignId}/characters/${hero.id}/review`, {
      body: { approve, comment: comment.trim() },
    });
    setComment("");
    await onDone();
  };

  return (
    <article className="card p-5 sm:p-6 border-2 border-accent/40 bg-surface shadow-xl flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
        <div>
          <span className="font-heading text-xl font-bold text-ink">{h.name}</span>
          <span className="font-mono text-xs text-accent ml-2">
            {[
              h.origin_name,
              h.class_name,
              h.derived?.hp_max ? `хиты ${h.derived.hp_max}` : null,
              h.derived?.ac ? `КД ${h.derived.ac}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
      </div>

      {h.derived?.abilities && (
        <div className="flex flex-wrap gap-2 text-xs font-mono">
          {ABILITIES.map((a) => (
            <span key={a} className="rounded-[6px] border border-line bg-raised px-2 py-0.5 text-ink-2">
              <span className="text-muted mr-1">{ABILITY_ABBR[a]}</span>
              <span className="font-semibold">{h.derived!.abilities![a]}</span>
            </span>
          ))}
        </div>
      )}

      {h.public_bio && (
        <div className="rounded-[8px] bg-raised/40 p-3 text-xs sm:text-sm text-ink-2 leading-relaxed">
          <span className="font-mono text-[10px] text-muted uppercase tracking-wider block mb-1">
            Публичное описание:
          </span>
          {h.public_bio}
        </div>
      )}

      {h.private_backstory && (
        <div className="rounded-[8px] border border-accent/30 bg-accent/5 p-3 text-xs sm:text-sm text-ink-2 leading-relaxed">
          <span className="font-mono text-[10px] text-accent uppercase tracking-wider block mb-1">
            Тайная предыстория героя (секрет для мастера):
          </span>
          {h.private_backstory}
        </div>
      )}

      {h.reviewer === "ai" && !h.review_error && (
        <p className="font-mono text-xs text-muted">
          Герой находится в очереди на проверку ИИ-мастером. Вы также можете одобрить его вручную.
        </p>
      )}

      {h.review_error && (
        <div className="rounded-[8px] border border-bad/40 bg-bad/10 p-2.5 font-mono text-xs text-bad">
          ИИ-мастер не смог провести проверку: {h.review_error.replace(/ \(.*$/s, "")}
        </div>
      )}

      <textarea
        className="field min-h-16 text-sm"
        placeholder="Комментарий мастерского состава игроку: одобрение, замечания или сюжетная зацепка..."
        maxLength={2000}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />

      <div className="flex flex-wrap items-center gap-2.5 pt-1">
        <ActionButton
          primary
          className="font-mono text-xs"
          run={review(true)}
          done={`${h.name} допущен в кампанию`}
        >
          ✓ ОДОБРИТЬ В ИГРУ
        </ActionButton>

        <ActionButton
          className="font-mono text-xs"
          run={review(false)}
          done="Герой возвращён игроку на доработку"
        >
          ВЕРНУТЬ НА ДОРАБОТКУ
        </ActionButton>

        {h.reviewer === "ai" && (
          <ActionButton
            className="font-mono text-xs ml-auto"
            run={async () => {
              await api(`/api/campaigns/${campaignId}/characters/${hero.id}/review/retry-ai`, { method: "POST" });
              await onDone();
            }}
            done="Проверка ИИ перезапущена"
          >
            Повторить проверку ИИ
          </ActionButton>
        )}
      </div>
    </article>
  );
}

/** Готовые герои: владелец собирает их заранее, игрок может взять любого вместо своего. */
function Premades({
  campaignId,
  premades,
  onChange,
}: {
  campaignId: string;
  premades: Reviewable[];
  onChange: () => Promise<unknown>;
}) {
  const [editing, setEditing] = useState<Reviewable | "new" | null>(null);
  const opts = useQuery({
    queryKey: ["options", campaignId],
    queryFn: () => api<BuilderOptions>(`/api/campaigns/${campaignId}/character-options`),
    enabled: !!editing,
  });

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">Готовые заготовки для игроков</h2>
          <p className="text-xs text-muted">
            Игроки смогут выбрать эти архетипы сразу вместо создания героя с нуля
          </p>
        </div>
        {!editing && (
          <button
            type="button"
            className="btn btn-outline-copper font-mono text-xs"
            onClick={() => setEditing("new")}
          >
            + ЗАГОТОВИТЬ ГЕРОЯ
          </button>
        )}
      </div>

      {!editing && premades.length === 0 && (
        <div className="card p-5 text-center text-xs text-muted border border-dashed">
          Заготовок пока нет. Вы можете собрать типовых персонажей под сюжет, чтобы новые игроки садились за стол мгновенно.
        </div>
      )}

      {!editing && premades.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {premades.map((p) => (
            <div key={p.id} className="card flex items-start justify-between gap-3 p-4 hover:border-accent/60 transition">
              <div className="min-w-0">
                <span className="block truncate font-heading text-base font-bold text-ink">
                  {p.name || "Без имени"}
                </span>
                <span className="block font-mono text-xs text-accent mt-0.5">
                  {[p.origin_name, p.class_name, p.errors?.length ? "не закончен" : null].filter(Boolean).join(" · ")}
                </span>
              </div>
              <div className="flex shrink-0 gap-1.5">
                <button
                  type="button"
                  className="btn px-2.5 py-1 text-xs font-mono"
                  onClick={() => setEditing(p)}
                >
                  Изменить
                </button>
                <ActionButton
                  danger
                  className="px-2 py-1 text-xs font-mono"
                  confirm={`Удалить заготовку «${p.name || "без имени"}»?`}
                  run={async () => {
                    await api(`/api/campaigns/${campaignId}/premades/${p.id}`, { method: "DELETE" });
                    await onChange();
                  }}
                  done="Заготовка удалена"
                >
                  Удалить
                </ActionButton>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <div className="flex flex-col gap-4 card p-5 border-2 border-accent/40 bg-surface">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <h3 className="font-heading text-xl font-bold text-ink">
              {editing === "new" ? "Новая заготовка персонажа" : `Редактирование: ${editing.name}`}
            </h3>
            <button
              type="button"
              className="btn font-mono text-xs"
              onClick={() => {
                setEditing(null);
                void onChange();
              }}
            >
              Завершить редактирование
            </button>
          </div>

          {opts.isError && (
            <div className="card border-bad/40 bg-bad/5 p-4 text-xs text-bad">
              Не удалось загрузить параметры: {(opts.error as Error).message}
            </div>
          )}

          {opts.data && (
            <Builder
              mode="premade"
              campaignId={campaignId}
              opts={opts.data}
              hero={editing === "new" ? null : editing}
              onSaved={() => void onChange()}
            />
          )}
        </div>
      )}
    </section>
  );
}
