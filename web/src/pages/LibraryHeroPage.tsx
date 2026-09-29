import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Header from "../components/Header";
import Builder from "../builder/Builder";
import { api } from "../lib/api";
import { HERO_STATUS_RU, type BuilderOptions, type LibraryHero, type World } from "../lib/builder";

/** Герой профиля: собирается для мира (или по базовым правилам) и потом копируется в любую кампанию. */
export default function LibraryHeroPage() {
  const param = useParams().hid;
  const hid = param === "new" ? undefined : param;
  const qc = useQueryClient();
  const navigate = useNavigate();
  // только что созданный герой: конструктор уже открыт с его данными, перезагружать его незачем
  const created = useRef(false);
  const hero = useQuery({
    queryKey: ["library", hid],
    queryFn: () => api<LibraryHero>(`/api/me/characters/${hid}`),
    enabled: !!hid,
  });
  const worlds = useQuery({ queryKey: ["worlds"], queryFn: () => api<World[]>("/api/me/worlds") });
  // выбранный мир; пока игрок не менял его, берём мир сохранённого героя
  const [picked, setPicked] = useState<string | null | undefined>(undefined);
  const packId = picked !== undefined ? picked : (hero.data?.pack_id ?? null);
  const opts = useQuery({
    queryKey: ["options", "library", packId],
    queryFn: () => api<BuilderOptions>(`/api/me/character-options${packId ? `?pack=${encodeURIComponent(packId)}` : ""}`),
    enabled: !hid || hero.isSuccess,
  });
  const problem = opts.error ?? hero.error ?? worlds.error;

  return (
    <>
      <Header>
        <Link
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          to="/"
          aria-label="К списку столов"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>
      </Header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Личная библиотека · Архив персонажей</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                {hid ? hero.data?.name || "Герой профиля" : "Новый герой библиотеки"}
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Героя можно собрать для мира или по базовым правилам SRD и взять копией в любую кампанию.
              </p>
            </div>

            {hid && hero.data && (
              <div className="self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
                УРОВЕНЬ: <span className="font-semibold text-accent">{hero.data.level}</span>
              </div>
            )}
          </div>
        </div>

        {worlds.data && worlds.data.length > 1 && (
          <label className="card flex flex-wrap items-center gap-3 p-4">
            <span>Мир героя</span>
            <select className="field max-w-xs" aria-label="Мир героя" value={packId ?? ""} onChange={(e) => setPicked(e.target.value || null)}>
              {worlds.data.map((w) => (
                <option key={w.id ?? ""} value={w.id ?? ""}>
                  {w.name}
                </option>
              ))}
            </select>
            <span className="text-sm text-muted">Конструктор предложит расы и классы этого мира.</span>
          </label>
        )}

        {problem ? (
          <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
            Не удалось загрузить данные героя: {(problem as Error).message}
          </div>
        ) : !opts.data || (hid && hero.isLoading && !created.current) ? (
          <div className="card p-8 text-center text-muted font-mono text-sm">
            Извлечение архивного листа персонажа…
          </div>
        ) : (
          <>
            <Builder
              // без hid в ключе: после первого сохранения URL меняется с /new на /:id, а конструктор
              // должен остаться тем же (шаг, броски, черновик), иначе игрока выкидывает на первый шаг
              key={`library-${packId ?? "base"}`}
              mode="library"
              packId={packId}
              opts={opts.data}
              hero={hid ? (hero.data ?? null) : null}
              onSaved={(h) => {
                void qc.invalidateQueries({ queryKey: ["library"] });
                if (!hid) {
                  created.current = true;
                  navigate(`/heroes/${h.id}`, { replace: true });
                }
              }}
            />

            {hero.data?.copies && hero.data.copies.length > 0 && (
              <section className="card p-5 sm:p-6 border border-line bg-surface">
                <h2 className="font-heading text-lg font-bold text-ink mb-1">
                  Активные копии в кампаниях
                </h2>
                <p className="text-xs text-muted mb-4">
                  Кампании, в которых сейчас участвуют экспедиционные копии этого персонажа
                </p>

                <div className="divide-y divide-line/60">
                  {hero.data.copies.map((c) => (
                    <div
                      key={c.character_id}
                      className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0"
                    >
                      <Link
                        to={`/c/${c.campaign_id}`}
                        className="text-sm font-semibold text-ink hover:text-accent transition flex items-center gap-1.5"
                      >
                        <span>{c.campaign_name}</span>
                        <span className="text-xs text-muted">→</span>
                      </Link>

                      <div className="flex items-center gap-2 font-mono text-xs">
                        <span className="text-muted">ур. {c.level}</span>
                        <span className="rounded-[6px] border border-line bg-raised px-2 py-0.5 text-accent">
                          {HERO_STATUS_RU[c.status] ?? c.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
