import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import Header from "../components/Header";
import Builder from "../builder/Builder";
import { api } from "../lib/api";
import { HERO_STATUS_RU, type BuilderOptions, type CampaignHero, type LibraryHero } from "../lib/builder";

interface Room {
  id: string;
  name: string;
  my_seat_id: string | null;
  my_role: string | null;
  pack_id: string | null;
}

/** Герой в кампании: выбрать готового, взять из профиля или собрать; дальше — проверка мастером. */
export default function CampaignHeroPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [building, setBuilding] = useState(false);
  const room = useQuery({ queryKey: ["room", id], queryFn: () => api<Room>(`/api/campaigns/${id}`) });
  const list = useQuery({
    queryKey: ["characters", id],
    queryFn: () => api<CampaignHero[]>(`/api/campaigns/${id}/characters`),
    // вердикт мастера приходит в игру событием; здесь, вне игры, просто переспрашиваем
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "submitted") ? 5000 : false),
  });
  const seat = room.data?.my_seat_id;
  const player = room.data?.my_role === "player";
  const library = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryHero[]>("/api/me/characters"),
    enabled: player,
  });
  const mine = list.data?.find((c) => seat && c.seat_id === seat && !["dead", "retired", "premade"].includes(c.status));
  const full = useQuery({
    queryKey: ["character", id, mine?.id],
    queryFn: () => api<CampaignHero>(`/api/campaigns/${id}/characters/${mine!.id}`),
    enabled: !!mine,
  });
  const opts = useQuery({
    queryKey: ["options", id],
    queryFn: () => api<BuilderOptions>(`/api/campaigns/${id}/character-options`),
    enabled: player,
  });

  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["characters", id] }), qc.invalidateQueries({ queryKey: ["character", id] }), qc.invalidateQueries({ queryKey: ["my-campaigns"] })]);
  const hero = mine ? (full.data ?? null) : null;
  const problem = room.error ?? list.error ?? opts.error ?? full.error;
  const loading = room.isLoading || list.isLoading || (player && opts.isLoading) || (!!mine && full.isLoading && !building);

  let body;
  if (problem) body = <p className="text-bad">Не удалось загрузить: {(problem as Error).message}</p>;
  else if (loading) body = <p className="text-muted">Загружаем…</p>;
  else if (!player)
    body = (
      <section className="card flex flex-col items-start gap-3 p-5">
        <p>Чтобы играть героем, займите место игрока за столом.</p>
        <ActionButton primary run={async () => { await api(`/api/campaigns/${id}/seats/take`, { method: "POST" }); await qc.invalidateQueries({ queryKey: ["room", id] }); await refresh(); }} done="Место занято">
          Занять место
        </ActionButton>
      </section>
    );
  else if (hero && hero.status === "submitted") body = <Waiting id={id} hero={hero} onRetry={refresh} />;
  else if (hero && ["approved", "active"].includes(hero.status))
    body = (
      <section className="card flex flex-col items-start gap-3 p-5">
        <p>
          <b>{hero.name}</b> в игре.
        </p>
        <Link className="btn btn-primary" to={`/c/${id}`}>
          К столу
        </Link>
      </section>
    );
  // черновик уже есть (в том числе копия героя из другого мира без класса) — только доработка в конструкторе
  else if (building || hero)
    body = (
      <>
        {hero?.review_comment && (
          <p className="card border-warn p-3 text-sm">
            Мастер вернул героя: {hero.review_comment}
          </p>
        )}
        <Builder
          mode="campaign"
          campaignId={id}
          opts={opts.data!}
          hero={hero}
          onSaved={() => void refresh()}
          onSubmitted={() => {
            setBuilding(false);
            void refresh();
          }}
        />
      </>
    );
  else
    body = (
      <Choose
        id={id}
        premades={(list.data ?? []).filter((c) => c.status === "premade" && !c.errors?.length)}
        library={library.data ?? []}
        packId={room.data?.pack_id ?? null}
        onNew={() => setBuilding(true)}
        onDone={refresh}
        openBuilder={() => setBuilding(true)}
      />
    );

  return (
    <>
      <Header>
        <button className="btn px-3 py-1" onClick={() => navigate(`/c/${id}`)}>
          ← {room.data?.name ?? "Кампания"}
        </button>
      </Header>
      <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6">
        <h1 className="text-2xl font-semibold">Герой кампании</h1>
        {body}
      </main>
    </>
  );
}

function Choose({
  id,
  premades,
  library,
  packId,
  onNew,
  onDone,
  openBuilder,
}: {
  id: string;
  premades: CampaignHero[];
  library: LibraryHero[];
  packId: string | null;
  onNew: () => void;
  onDone: () => Promise<unknown>;
  openBuilder: () => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      {premades.length > 0 && (
        <Group title="Готовые герои от владельца">
          {premades.map((p) => (
            <Pick key={p.id} name={p.name} sub={[p.origin_name, p.class_name, p.derived?.hp_max ? `хиты ${p.derived.hp_max}` : null]} bio={p.public_bio}>
              <ActionButton primary run={async () => { await api(`/api/campaigns/${id}/characters/${p.id}/claim`, { method: "POST" }); await onDone(); }} done="Герой ваш">
                Играть им
              </ActionButton>
            </Pick>
          ))}
        </Group>
      )}
      {library.length > 0 && (
        <Group title="Мои герои из профиля">
          {library.map((h) => (
            <Pick
              key={h.id}
              name={h.name}
              sub={[
                h.origin_name,
                h.class_name,
                h.errors.length ? "не закончен" : null,
                // собран для другого мира: чего нет в этом мире, игрок выберет заново в конструкторе
                (h.pack_id ?? null) !== packId ? `из мира «${h.world_name}», часть выбора придётся заменить` : null,
              ]}
              bio={h.public_bio}
            >
              <ActionButton
                run={async () => {
                  // копия встаёт черновиком; готовую сразу отправляем мастеру, иначе открываем на доработку
                  const copy = await api<CampaignHero>(`/api/campaigns/${id}/characters/from-library/${h.id}`, { method: "POST" });
                  if (!copy.errors?.length) {
                    const r = await api<{ errors: string[] }>(`/api/campaigns/${id}/characters/${copy.id}/submit`, { method: "POST" });
                    if (!r.errors.length) return onDone();
                  }
                  openBuilder();
                  await onDone();
                }}
                done="Копия в кампании"
              >
                Взять копию
              </ActionButton>
            </Pick>
          ))}
        </Group>
      )}
      <section className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <span>Собрать нового героя по правилам этой кампании</span>
        <button className="btn btn-primary" onClick={onNew}>
          Создать героя
        </button>
      </section>
    </div>
  );
}

function Waiting({ id, hero, onRetry }: { id: string; hero: CampaignHero; onRetry: () => Promise<unknown> }) {
  const ai = hero.reviewer === "ai";
  return (
    <section className="card flex flex-col items-start gap-3 p-5">
      <p>
        <b>{hero.name}</b> · {HERO_STATUS_RU.submitted} у {ai ? "ИИ-мастера" : "мастера"}.
      </p>
      {hero.review_error ? (
        <>
          <p className="text-sm text-bad">
            ИИ-мастер не смог проверить героя: {hero.review_error.replace(/ \(.*$/s, "")}. Владелец кампании может проверить его сам.
          </p>
          <ActionButton run={async () => { await api(`/api/campaigns/${id}/characters/${hero.id}/review/retry-ai`, { method: "POST" }); await onRetry(); }} done="Проверка запущена снова">
            Повторить проверку ИИ
          </ActionButton>
        </>
      ) : (
        <p className="text-sm text-muted">Как только мастер ответит, здесь появится решение. Страницу можно закрыть.</p>
      )}
      <Link className="btn" to={`/c/${id}`}>
        К столу
      </Link>
    </section>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg text-muted">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Pick({ name, sub, bio, children }: { name: string; sub: (string | null | undefined)[]; bio?: string | null; children: ReactNode }) {
  return (
    <div className="card flex flex-col gap-2 p-4">
      <div>
        <p className="font-semibold">{name || "Без имени"}</p>
        <p className="text-xs text-muted">{sub.filter(Boolean).join(" · ")}</p>
        {bio && <p className="mt-1 line-clamp-3 text-sm text-muted">{bio}</p>}
      </div>
      <div>{children}</div>
    </div>
  );
}
