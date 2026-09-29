import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import Header from "../components/Header";
import Builder from "../builder/Builder";
import PersonaEditor from "../components/PersonaEditor";
import { api } from "../lib/api";
import { HERO_STATUS_RU, type BuilderOptions, type CampaignHero, type LibraryHero } from "../lib/builder";

interface Room {
  id: string;
  name: string;
  my_seat_id: string | null;
  my_role: string | null;
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

  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["characters", id] }),
      qc.invalidateQueries({ queryKey: ["character", id] }),
      qc.invalidateQueries({ queryKey: ["my-campaigns"] }),
    ]);

  const hero = mine ? full.data ?? null : null;
  const problem = room.error ?? list.error ?? opts.error ?? full.error;
  const loading = room.isLoading || list.isLoading || (player && opts.isLoading) || (!!mine && full.isLoading && !building);

  let body;
  if (problem) {
    body = (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось загрузить данные: {(problem as Error).message}
      </div>
    );
  } else if (loading) {
    body = (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Сверяем судовые списки и правила кампании…
      </div>
    );
  } else if (!player) {
    body = (
      <section className="card flex flex-col items-start gap-4 p-6 border-line bg-surface">
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">Место игрока не занято</h2>
          <p className="mt-1 text-sm text-muted">
            Чтобы играть героем за этим столом, необходимо занять свободное место в составе отряда.
          </p>
        </div>
        <ActionButton
          primary
          className="font-mono text-xs tracking-wider"
          run={async () => {
            await api(`/api/campaigns/${id}/seats/take`, { method: "POST" });
            await qc.invalidateQueries({ queryKey: ["room", id] });
            await refresh();
          }}
          done="Вы заняли место за столом"
        >
          ЗАНЯТЬ МЕСТО ИГРОКА
        </ActionButton>
      </section>
    );
  } else if (hero && hero.status === "submitted") {
    body = <Waiting id={id} hero={hero} onRetry={refresh} />;
  } else if (hero && ["approved", "active"].includes(hero.status)) {
    body = (
      <section className="card flex flex-col items-start gap-4 p-6 border-patina/40 bg-patina/5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-patina/20 border border-patina text-patina-hi font-bold">
            ✓
          </span>
          <div>
            <h2 className="font-heading text-xl font-bold text-ink">{hero.name}</h2>
            <p className="font-mono text-xs text-patina-hi">
              Герой утверждён мастером и готов к игре в составе отряда
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2.5 pt-2">
          <Link className="btn btn-primary font-mono text-xs tracking-wider" to={`/c/${id}`}>
            ВОЙТИ В ИГРУ (К СТОЛУ) →
          </Link>
          <button
            type="button"
            className="btn btn-outline-copper font-mono text-xs"
            onClick={() => setBuilding(true)}
          >
            Просмотреть лист в конструкторе
          </button>
        </div>
      </section>
    );
    body = (
      <div className="flex flex-col gap-5">
        {body}
        <section className="card flex flex-col gap-4 p-5 sm:p-6 border border-line bg-surface">
          <div className="border-b border-line pb-3">
            <h2 className="font-heading text-xl font-bold text-ink">Характер героя</h2>
            <p className="mt-0.5 text-xs text-muted">
              Необязательно, но мастер это видит и подстраивает сцены. Пишите своими словами, поля — подсказки.
            </p>
          </div>
          <PersonaEditor base={`/api/campaigns/${id}/characters/${hero.id}/persona`} />
        </section>
      </div>
    );
  } else if (building || (hero && (hero.sheet as Record<string, unknown> | null)?.class_id)) {
    body = (
      <div className="flex flex-col gap-5">
        {hero?.review_comment && (
          <div className="card border-warn/40 bg-warn/10 p-4">
            <div className="flex items-center gap-2 font-mono text-xs font-bold text-warn uppercase tracking-wider mb-1">
              <span>⚠ Замечания мастера к герою:</span>
            </div>
            <p className="text-sm text-ink">{hero.review_comment}</p>
          </div>
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
      </div>
    );
  } else {
    body = (
      <Choose
        id={id}
        premades={(list.data ?? []).filter((c) => c.status === "premade" && !c.errors?.length)}
        library={library.data ?? []}
        onNew={() => setBuilding(true)}
        onDone={refresh}
        openBuilder={() => setBuilding(true)}
      />
    );
  }

  return (
    <>
      <Header>
        <button
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          onClick={() => navigate(`/c/${id}`)}
          aria-label="Вернуться к столу кампании"
        >
          <span>←</span>
          <span className="truncate max-w-[180px] sm:max-w-xs">{room.data?.name ?? "Кампания"}</span>
        </button>
      </Header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Судовая канцелярия · Персонаж</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                Герой кампании
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Создайте нового исследователя, возьмите готовую заготовку мастера или скопируйте героя из библиотеки.
              </p>
            </div>

            {room.data && (
              <div className="self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
                СТОЛ: <span className="font-semibold text-accent">{room.data.name}</span>
              </div>
            )}
          </div>
        </div>

        {body}
      </main>
    </>
  );
}

function Choose({
  id,
  premades,
  library,
  onNew,
  onDone,
  openBuilder,
}: {
  id: string;
  premades: CampaignHero[];
  library: LibraryHero[];
  onNew: () => void;
  onDone: () => Promise<unknown>;
  openBuilder: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      {/* Create New Hero Callout */}
      <section className="card p-5 sm:p-6 border-2 border-accent/40 bg-surface hover:border-accent transition">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="font-mono text-[11px] text-accent font-semibold uppercase tracking-wider">
              Чистый лист
            </div>
            <h2 className="font-heading text-xl sm:text-2xl font-bold text-ink mt-0.5">
              Собрать нового героя
            </h2>
            <p className="text-xs sm:text-sm text-muted mt-1 max-w-xl">
              Пошаговый конструктор по правилам этой кампании: класс, происхождение, характеристики, навыки и экипировка.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary self-start sm:self-center font-mono text-xs sm:text-sm tracking-wider whitespace-nowrap"
            onClick={onNew}
          >
            + СОЗДАТЬ ГЕРОЯ
          </button>
        </div>
      </section>

      {/* Premade heroes from campaign master */}
      {premades.length > 0 && (
        <Group
          title="Заготовки героев от мастера кампании"
          subtitle="Сбалансированные архетипы, подготовленные специально под этот сюжет"
        >
          {premades.map((p) => (
            <Pick
              key={p.id}
              name={p.name}
              sub={[p.origin_name, p.class_name, p.derived?.hp_max ? `хиты ${p.derived.hp_max}` : null]}
              bio={p.public_bio}
            >
              <ActionButton
                primary
                className="font-mono text-xs w-full sm:w-auto"
                run={async () => {
                  await api(`/api/campaigns/${id}/characters/${p.id}/claim`, { method: "POST" });
                  await onDone();
                }}
                done="Герой выбран"
              >
                ВЫБРАТЬ ЭТОГО ГЕРОЯ
              </ActionButton>
            </Pick>
          ))}
        </Group>
      )}

      {/* Library heroes from profile */}
      {library.length > 0 && (
        <Group
          title="Герои из вашей личной библиотеки"
          subtitle="Копия выбранного героя будет перенесена в кампанию и проверена мастером"
        >
          {library.map((h) => (
            <Pick
              key={h.id}
              name={h.name}
              sub={[h.origin_name, h.class_name, h.errors.length ? "черновик" : "готов"]}
              bio={h.public_bio}
            >
              <ActionButton
                className="font-mono text-xs w-full sm:w-auto"
                run={async () => {
                  const copy = await api<CampaignHero>(`/api/campaigns/${id}/characters/from-library/${h.id}`, {
                    method: "POST",
                  });
                  if (!copy.errors?.length) {
                    const r = await api<{ errors: string[] }>(`/api/campaigns/${id}/characters/${copy.id}/submit`, {
                      method: "POST",
                    });
                    if (!r.errors.length) return onDone();
                  }
                  openBuilder();
                  await onDone();
                }}
                done="Копия добавлена в кампанию"
              >
                ВЗЯТЬ КОПИЮ В КАМПАНИЮ
              </ActionButton>
            </Pick>
          ))}
        </Group>
      )}
    </div>
  );
}

function Waiting({ id, hero, onRetry }: { id: string; hero: CampaignHero; onRetry: () => Promise<unknown> }) {
  const ai = hero.reviewer === "ai";
  return (
    <section className="card flex flex-col items-start gap-4 p-6 border-accent/40 bg-surface">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full border border-accent bg-accent/15 text-accent animate-pulse">
          ⏳
        </span>
        <div>
          <h2 className="font-heading text-xl font-bold text-ink">{hero.name}</h2>
          <p className="font-mono text-xs text-accent">
            {HERO_STATUS_RU.submitted} · Ожидает проверки {ai ? "ИИ-мастером" : "мастером стола"}
          </p>
        </div>
      </div>

      {hero.review_error ? (
        <div className="rounded-[10px] border border-bad/40 bg-bad/10 p-4 text-sm text-bad w-full">
          <p className="font-semibold">ИИ-мастер не смог завершить проверку:</p>
          <p className="mt-1 font-mono text-xs">{hero.review_error.replace(/ \(.*$/s, "")}</p>
          <div className="mt-3">
            <ActionButton
              className="font-mono text-xs"
              run={async () => {
                await api(`/api/campaigns/${id}/characters/${hero.id}/review/retry-ai`, { method: "POST" });
                await onRetry();
              }}
              done="Повторная проверка запущена"
            >
              ПОВТОРИТЬ ПРОВЕРКУ ИИ
            </ActionButton>
          </div>
        </div>
      ) : (
        <p className="text-xs sm:text-sm text-muted">
          Мастер изучает биографию, навыки и соответствие правилам сеттинга.
          После одобрения герой автоматически появится за столом. Страницу можно закрыть.
        </p>
      )}

      <div className="flex gap-3 pt-2">
        <Link className="btn btn-outline-copper font-mono text-xs" to={`/c/${id}`}>
          Вернуться к столу
        </Link>
      </div>
    </section>
  );
}

function Group({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="font-heading text-lg sm:text-xl font-bold text-ink">{title}</h2>
        {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function Pick({
  name,
  sub,
  bio,
  children,
}: {
  name: string;
  sub: (string | null | undefined)[];
  bio?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="card group relative flex flex-col justify-between gap-3 p-5 transition hover:border-accent/60">
      <div>
        <div className="flex items-baseline justify-between gap-2 border-b border-line pb-2 mb-2">
          <p className="font-heading text-lg font-bold text-ink group-hover:text-accent transition">
            {name || "Без имени"}
          </p>
          <span className="font-mono text-[11px] text-accent">
            {sub.filter(Boolean).join(" · ")}
          </span>
        </div>
        {bio && <p className="line-clamp-3 text-xs text-muted leading-relaxed">{bio}</p>}
      </div>
      <div className="pt-2">{children}</div>
    </div>
  );
}
