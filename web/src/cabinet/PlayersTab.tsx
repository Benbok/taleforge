import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import Avatar from "../components/Avatar";
import Builder from "../builder/Builder";
import { ABILITIES, ABILITY_ABBR } from "../game/hero";
import { api } from "../lib/api";
import type { BuilderOptions, CampaignHero } from "../lib/builder";
import type { Room } from "../lib/campaign";
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
    <div className="flex flex-col gap-5">
      <section className="card flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Места за столом</h2>
          {room.is_owner && !room.my_seat_id && (
            <ActionButton
              run={async () => onRoom(await api<Room>(`/api/campaigns/${id}/seats/take`, { method: "POST" }))}
              done="Вы заняли место игрока"
            >
              Занять место игрока
            </ActionButton>
          )}
        </div>
        <ul className="flex flex-col gap-2">
          {players.map((s) => {
            const h = heroOf(s.id);
            return (
              <li key={s.id} className="flex flex-wrap items-center gap-3">
                <Avatar name={h?.name ?? s.user_name} role={s.role} occupant={s.occupant_type} presence={null} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {s.occupant_type === "empty" ? "Свободное место" : s.occupant_type === "agent" ? "ИИ-игрок" : s.user_name}
                    {s.id === room.my_seat_id && <span className="text-muted"> (вы)</span>}
                  </span>
                  {s.occupant_type !== "empty" && (
                    <span className="block text-xs text-muted">{h ? `${h.name} · ${heroState(h.status)}` : "героя ещё нет"}</span>
                  )}
                </span>
                {room.is_owner && s.occupant_type === "human" && s.id !== room.my_seat_id && (
                  <ActionButton
                    danger
                    className="px-2 py-0.5 text-xs"
                    confirm={`Освободить место игрока ${s.user_name}? Его герой останется в кампании.`}
                    run={async () => onRoom(await api<Room>(`/api/campaigns/${id}/seats/${s.id}/occupant`, { method: "DELETE" }))}
                    done="Место освобождено"
                  >
                    Освободить
                  </ActionButton>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {room.is_owner && (
        <section className="card flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">Приглашения</h2>
            <ActionButton
              primary
              run={async () => {
                const inv = await api<Invite>(`/api/campaigns/${id}/invites`, { body: {} });
                await qc.invalidateQueries({ queryKey: ["invites", id] });
                await copy(inv.url);
              }}
            >
              Новая ссылка
            </ActionButton>
          </div>
          {invites.isError && <p className="text-bad">Не удалось загрузить приглашения: {(invites.error as Error).message}</p>}
          {invites.isSuccess && live.length === 0 && <p className="text-sm text-muted">Действующих ссылок нет. Новая действует 3 дня.</p>}
          <ul className="flex flex-col gap-2">
            {live.map((i) => (
              <li key={i.token} className="flex flex-wrap items-center gap-2">
                <input className="field min-w-0 basis-full text-xs sm:basis-0 sm:flex-1" readOnly value={i.url} onFocus={(e) => e.currentTarget.select()} aria-label="Ссылка-приглашение" />
                <span className="text-xs text-muted">
                  {i.expires_at ? `до ${DATE.format(new Date(i.expires_at))}` : "бессрочно"}
                  {i.uses ? ` · вошли ${i.uses}` : ""}
                </span>
                <button className="btn px-2 py-0.5 text-xs" onClick={() => void copy(i.url)}>
                  Копировать
                </button>
                <ActionButton
                  className="px-2 py-0.5 text-xs"
                  run={async () => {
                    await api(`/api/campaigns/${id}/invites/${i.token}`, { method: "DELETE" });
                    await qc.invalidateQueries({ queryKey: ["invites", id] });
                  }}
                  done="Ссылка отозвана"
                >
                  Отозвать
                </ActionButton>
              </li>
            ))}
          </ul>
        </section>
      )}

      {waiting.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg text-muted">Ждут проверки</h2>
          {waiting.map((c) => (
            <ReviewCard key={c.id} campaignId={id} hero={c} onDone={refreshChars} />
          ))}
        </section>
      )}

      {room.is_owner && <Premades campaignId={id} premades={premades} onChange={refreshChars} />}
    </div>
  );
}

function heroState(status: string): string {
  return { draft: "собирает героя", submitted: "на проверке", approved: "готов", active: "готов" }[status] ?? status;
}

async function copy(url: string) {
  try {
    await navigator.clipboard.writeText(url);
    toast.ok("Ссылка скопирована");
  } catch {
    toast.info(`Ссылка: ${url}`);
  }
}

/** Герой на проверке: лист, история и тайная предыстория (её видит только проверяющий). */
function ReviewCard({ campaignId, hero, onDone }: { campaignId: string; hero: Reviewable; onDone: () => Promise<unknown> }) {
  const [comment, setComment] = useState("");
  const full = useQuery({
    queryKey: ["character", campaignId, hero.id],
    queryFn: () => api<Reviewable>(`/api/campaigns/${campaignId}/characters/${hero.id}`),
  });
  const h = full.data ?? hero;
  const review = (approve: boolean) => async () => {
    if (!approve && !comment.trim()) throw new Error("Напишите игроку, что поправить");
    await api(`/api/campaigns/${campaignId}/characters/${hero.id}/review`, { body: { approve, comment: comment.trim() } });
    setComment("");
    await onDone();
  };
  return (
    <article className="card flex flex-col gap-3 p-4">
      <div>
        <p className="font-semibold">{h.name}</p>
        <p className="text-xs text-muted">
          {[h.origin_name, h.class_name, h.derived?.hp_max ? `хиты ${h.derived.hp_max}` : null, h.derived?.ac ? `КД ${h.derived.ac}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {h.derived?.abilities && (
          <p className="text-xs">{ABILITIES.map((a) => `${ABILITY_ABBR[a]} ${h.derived!.abilities![a]}`).join(" · ")}</p>
        )}
      </div>
      {h.public_bio && <p className="text-sm">{h.public_bio}</p>}
      {h.private_backstory && (
        <p className="rounded-md border border-line p-2 text-sm">
          <span className="text-xs text-muted">Тайна героя: </span>
          {h.private_backstory}
        </p>
      )}
      {h.reviewer === "ai" && !h.review_error && <p className="text-sm text-muted">Сейчас героя проверяет ИИ-мастер. Можно решить и самому.</p>}
      {h.review_error && <p className="text-sm text-bad">ИИ-мастер не смог проверить: {h.review_error.replace(/ \(.*$/s, "")}</p>}
      <textarea
        className="field min-h-14 text-sm"
        placeholder="Комментарий игроку: что понравилось или что поправить"
        maxLength={2000}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <ActionButton primary run={review(true)} done={`${h.name} в игре`}>
          Одобрить
        </ActionButton>
        <ActionButton run={review(false)} done="Герой вернулся игроку">
          Вернуть на доработку
        </ActionButton>
        {h.reviewer === "ai" && (
          <ActionButton
            run={async () => {
              await api(`/api/campaigns/${campaignId}/characters/${hero.id}/review/retry-ai`, { method: "POST" });
              await onDone();
            }}
            done="ИИ-мастер проверит ещё раз"
          >
            Повторить проверку ИИ
          </ActionButton>
        )}
      </div>
    </article>
  );
}

/** Готовые герои: владелец собирает их заранее, игрок может взять любого вместо своего. */
function Premades({ campaignId, premades, onChange }: { campaignId: string; premades: Reviewable[]; onChange: () => Promise<unknown> }) {
  const [editing, setEditing] = useState<Reviewable | "new" | null>(null);
  const opts = useQuery({
    queryKey: ["options", campaignId],
    queryFn: () => api<BuilderOptions>(`/api/campaigns/${campaignId}/character-options`),
    enabled: !!editing,
  });
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg text-muted">Готовые герои для игроков</h2>
        {!editing && (
          <button className="btn" onClick={() => setEditing("new")}>
            Заготовить героя
          </button>
        )}
      </div>
      {!editing && premades.length === 0 && (
        <p className="text-sm text-muted">Заготовки пригодятся тем, кто хочет сразу играть: игрок выбирает героя и садится за стол.</p>
      )}
      {!editing && (
        <div className="grid gap-3 sm:grid-cols-2">
          {premades.map((p) => (
            <div key={p.id} className="card flex items-start justify-between gap-3 p-4">
              <span className="min-w-0">
                <span className="block truncate font-semibold">{p.name || "Без имени"}</span>
                <span className="block text-xs text-muted">
                  {[p.origin_name, p.class_name, p.errors?.length ? "не закончен, игрокам не виден" : null].filter(Boolean).join(" · ")}
                </span>
              </span>
              <span className="flex shrink-0 gap-1.5">
                <button className="btn px-2 py-0.5 text-xs" onClick={() => setEditing(p)}>
                  Изменить
                </button>
                <ActionButton
                  danger
                  className="px-2 py-0.5 text-xs"
                  confirm={`Удалить заготовку «${p.name || "без имени"}»?`}
                  run={async () => {
                    await api(`/api/campaigns/${campaignId}/premades/${p.id}`, { method: "DELETE" });
                    await onChange();
                  }}
                  done="Заготовка удалена"
                >
                  Удалить
                </ActionButton>
              </span>
            </div>
          ))}
        </div>
      )}
      {editing && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <p>{editing === "new" ? "Новая заготовка" : `Заготовка «${editing.name}»`}</p>
            <button
              className="btn"
              onClick={() => {
                setEditing(null);
                void onChange();
              }}
            >
              Готово
            </button>
          </div>
          {opts.isError && <p className="text-bad">Не удалось загрузить варианты: {(opts.error as Error).message}</p>}
          {opts.data && (
            <Builder mode="premade" campaignId={campaignId} opts={opts.data} hero={editing === "new" ? null : editing} onSaved={() => void onChange()} />
          )}
        </div>
      )}
    </section>
  );
}
