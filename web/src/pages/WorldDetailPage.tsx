import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import Header from "../components/Header";
import { api } from "../lib/api";
import type { WorldDetail } from "../lib/worlds";
import { useSession } from "../stores/session";

type TabKey = "overview" | "factions" | "locations" | "characters" | "mechanics" | "bestiary";

export default function WorldDetailPage() {
  const { worldId } = useParams<{ worldId: string }>();
  const user = useSession((s) => s.user);
  const isAdmin = user ? user.platform_role !== "player" : false;

  const { data: world, isLoading, error } = useQuery({
    queryKey: ["world-detail", worldId],
    queryFn: () => api<WorldDetail>(`/api/worlds/${worldId}`),
    enabled: !!worldId,
  });

  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-base text-ink">
        <Header>
          <Link
            to="/"
            className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          >
            <span>←</span>
            <span>К СПИСКУ МИРОВ</span>
          </Link>
        </Header>
        <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-12 md:px-8 text-center">
          <div className="card p-12 text-muted font-mono text-sm">
            Загрузка летописей и атласа мира…
          </div>
        </main>
      </div>
    );
  }

  if (error || !world) {
    return (
      <div className="min-h-screen bg-base text-ink">
        <Header>
          <Link
            to="/"
            className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          >
            <span>←</span>
            <span>К СПИСКУ МИРОВ</span>
          </Link>
        </Header>
        <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-12 md:px-8">
          <div className="card border-bad/40 bg-bad/5 p-8 text-center">
            <h2 className="font-heading text-2xl font-bold text-bad">Мир не найден</h2>
            <p className="mt-2 text-sm text-muted">
              Пакет сеттинга «{worldId}» не зарегистрирован в системе или был удалён.
            </p>
            <div className="mt-6">
              <Link to="/" className="btn btn-primary text-xs">
                Вернуться на главную
              </Link>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // Определяем доступные вкладки
  const hasFactions = world.factions && world.factions.length > 0;
  const hasLocations = world.locations && world.locations.length > 0;
  const hasCharacters = (world.origins && world.origins.length > 0) || (world.classes && world.classes.length > 0);
  const hasMechanics = (world.scales && world.scales.length > 0) || (world.clocks && world.clocks.length > 0);
  const hasBestiary = world.bestiary && world.bestiary.length > 0;

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "overview", label: "Обзор и Лор", count: world.lore_topics?.reduce((acc, t) => acc + t.facts.length, 0) },
    ...(hasFactions ? [{ key: "factions" as TabKey, label: "Фракции", count: world.factions.length }] : []),
    ...(hasLocations ? [{ key: "locations" as TabKey, label: "Атлас и Локации", count: world.locations.length }] : []),
    ...(hasCharacters ? [{ key: "characters" as TabKey, label: "Народы и Классы", count: (world.origins?.length || 0) + (world.classes?.length || 0) }] : []),
    ...(hasMechanics ? [{ key: "mechanics" as TabKey, label: "Шкалы и Механики", count: (world.scales?.length || 0) + (world.clocks?.length || 0) }] : []),
    ...(hasBestiary ? [{ key: "bestiary" as TabKey, label: "Бестиарий", count: world.counts?.creature_template || world.bestiary.length }] : []),
  ];

  const currentTopic = selectedTopic
    ? world.lore_topics.find((t) => t.topic === selectedTopic)
    : world.lore_topics[0];

  return (
    <div className="min-h-screen bg-base text-ink pb-16">
      <Header>
        <Link
          to="/"
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          aria-label="К каталогу миров"
        >
          <span>←</span>
          <span>К КАТАЛОГУ МИРОВ</span>
        </Link>
      </Header>

      <main className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-8 md:px-8">
        {/* Баннер мира */}
        <div className="relative overflow-hidden rounded-[16px] border border-line bg-surface p-6 sm:p-8">
          <div className="pointer-events-none absolute -right-10 -top-10 h-64 w-64 rounded-full bg-accent/10 blur-3xl" />
          
          <div className="relative flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="font-mono text-xs tracking-widest text-copper-hi uppercase">
                {world.category}
              </span>
              <div className="flex items-center gap-2">
                <span className="rounded bg-raised px-2.5 py-1 font-mono text-[11px] text-muted border border-line">
                  v{world.version}
                </span>
                <span className="rounded bg-accent/15 px-2.5 py-1 font-mono text-[11px] text-accent font-semibold border border-accent/30">
                  {world.status_badge}
                </span>
              </div>
            </div>

            <div>
              <h1 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-ink">
                {world.name}
              </h1>
              <p className="mt-3 font-narration text-lg sm:text-xl italic leading-relaxed text-ink-2 max-w-4xl">
                {world.description || world.summary}
              </p>
            </div>

            {/* Плашки параметров */}
            <div className="mt-2 flex flex-wrap gap-2 font-mono text-xs text-muted">
              {world.badges.map((b, idx) => (
                <span key={idx} className="rounded-md border border-line bg-raised px-3 py-1.5">
                  {b}
                </span>
              ))}
              {world.ruleset_base && (
                <span className="rounded-md border border-line bg-raised px-3 py-1.5">
                  База: {world.ruleset_base}
                </span>
              )}
            </div>

            {/* Действия */}
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line-soft pt-5">
              {isAdmin && (
                <Link
                  to={`/new?pack=${world.id}`}
                  className="btn btn-primary text-xs font-semibold px-4 py-2"
                >
                  Запустить стол по миру
                </Link>
              )}
              <Link
                to={`/heroes/new?pack=${world.id}`}
                className="btn btn-outline-copper text-xs font-semibold px-4 py-2"
              >
                Создать героя в этом мире
              </Link>
              {world.license && (
                <span className="ml-auto text-[11px] text-muted font-mono max-w-xs truncate" title={world.license}>
                  {world.license}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Навигация по разделам мира */}
        <div className="flex border-b border-line overflow-x-auto gap-2 pb-1 scrollbar-none">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 whitespace-nowrap rounded-t-lg px-4 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? "border-b-2 border-accent text-accent bg-raised/50"
                    : "text-muted hover:text-ink hover:bg-raised/20"
                }`}
              >
                <span>{tab.label}</span>
                {tab.count !== undefined && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-mono ${
                      isActive ? "bg-accent/20 text-accent" : "bg-raised text-muted"
                    }`}
                  >
                    {tab.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Контент активного раздела */}
        <div className="flex flex-col gap-6">
          {/* Вкладка 1: Обзор и Лор */}
          {activeTab === "overview" && (
            <div className="grid gap-6 lg:grid-cols-4">
              {/* Левая колонка: список тем канона */}
              {world.lore_topics && world.lore_topics.length > 0 ? (
                <>
                  <div className="lg:col-span-1 flex flex-col gap-1.5">
                    <div className="font-mono text-xs uppercase tracking-wider text-muted px-2 pb-1">
                      Хроники и темы канона
                    </div>
                    {world.lore_topics.map((t) => {
                      const isSel = (currentTopic?.topic === t.topic);
                      return (
                        <button
                          key={t.topic}
                          type="button"
                          onClick={() => setSelectedTopic(t.topic)}
                          className={`flex items-center justify-between text-left rounded-lg px-3 py-2 text-xs transition ${
                            isSel
                              ? "bg-accent text-bg font-semibold"
                              : "bg-surface text-ink-2 hover:bg-raised hover:text-ink border border-line"
                          }`}
                        >
                          <span className="truncate">{t.title}</span>
                          <span className={`text-[10px] font-mono ml-2 ${isSel ? "text-bg/80" : "text-muted"}`}>
                            {t.facts.length}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {/* Правая колонка: факты выбранной темы */}
                  <div className="lg:col-span-3 flex flex-col gap-4">
                    {currentTopic && (
                      <div className="card p-6 border-line bg-surface flex flex-col gap-4">
                        <div className="border-b border-line-soft pb-3">
                          <h2 className="font-heading text-2xl font-semibold text-ink">
                            {currentTopic.title}
                          </h2>
                          <p className="text-xs text-muted font-mono mt-1">
                            {currentTopic.facts.length} фактов канона мира
                          </p>
                        </div>

                        <div className="grid gap-4 sm:grid-cols-2">
                          {currentTopic.facts.map((fact) => (
                            <div
                              key={fact.id}
                              className="rounded-lg border border-line/80 bg-raised/40 p-4 flex flex-col justify-between gap-2"
                            >
                              <div>
                                <h3 className="font-heading text-base font-semibold text-ink">
                                  {fact.name}
                                </h3>
                                <p className="mt-1.5 font-narration text-sm leading-relaxed text-ink-2">
                                  {fact.text}
                                </p>
                              </div>
                              {fact.tags && fact.tags.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-2">
                                  {fact.tags.map((tg) => (
                                    <span
                                      key={tg}
                                      className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-mono text-muted border border-line/50"
                                    >
                                      #{tg}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <div className="lg:col-span-4 card p-8 text-center text-muted">
                  <p className="font-narration text-base italic">{world.description}</p>
                </div>
              )}
            </div>
          )}

          {/* Вкладка 2: Фракции */}
          {activeTab === "factions" && (
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {world.factions.map((f) => (
                <article
                  key={f.id}
                  className="card p-5 border-line bg-surface flex flex-col justify-between gap-4"
                >
                  <div className="flex flex-col gap-2.5">
                    <h3 className="font-heading text-xl font-semibold text-ink">
                      {f.name}
                    </h3>
                    <p className="font-narration text-sm leading-relaxed text-ink-2">
                      {f.description}
                    </p>
                    {f.goal && (
                      <div className="rounded-md border border-line/60 bg-raised/50 p-2.5 mt-1">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-copper-hi">
                          Цель
                        </div>
                        <p className="text-xs text-ink-2 mt-0.5">{f.goal}</p>
                      </div>
                    )}
                  </div>

                  {f.resources && f.resources.length > 0 && (
                    <div className="border-t border-line-soft pt-3">
                      <div className="font-mono text-[10px] uppercase tracking-wider text-muted mb-1.5">
                        Ресурсы и влияние
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {f.resources.map((res, idx) => (
                          <span
                            key={idx}
                            className="rounded bg-raised px-2 py-0.5 text-[11px] text-muted border border-line/60"
                          >
                            {res}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          {/* Вкладка 3: Атлас и локации */}
          {activeTab === "locations" && (
            <div className="grid gap-6 md:grid-cols-2">
              {world.locations.map((loc) => (
                <article
                  key={loc.id}
                  className="card p-6 border-line bg-surface flex flex-col justify-between gap-4"
                >
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] text-copper-hi uppercase">
                        {loc.location_type === "hulk"
                          ? "Город на туше"
                          : loc.location_type === "belt"
                          ? "Пояс рубежа"
                          : loc.location_type || "Опорная локация"}
                      </span>
                      {loc.population && (
                        <span className="font-mono text-[11px] text-muted">
                          Население: ~{loc.population.toLocaleString("ru-RU")}
                        </span>
                      )}
                    </div>

                    <h3 className="font-heading text-2xl font-semibold text-ink">
                      {loc.name}
                    </h3>
                    <p className="font-narration text-sm leading-relaxed text-ink-2">
                      {loc.description}
                    </p>

                    {loc.ruler && (
                      <div className="text-xs text-muted">
                        <span className="font-mono text-[10px] uppercase text-ink-2 mr-1">Власть:</span>
                        {loc.ruler}
                      </div>
                    )}

                    {loc.districts && loc.districts.length > 0 && (
                      <div className="mt-2 flex flex-col gap-1.5 border-t border-line-soft pt-3">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-muted">
                          Ключевые районы
                        </div>
                        <div className="grid gap-2 sm:grid-cols-2">
                          {loc.districts.map((d, idx) => (
                            <div key={idx} className="rounded bg-raised/60 p-2 border border-line/50">
                              <div className="font-semibold text-xs text-ink">{d.name}</div>
                              {d.text && <div className="text-[11px] text-muted mt-0.5">{d.text}</div>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}

          {/* Вкладка 4: Народы и Классы */}
          {activeTab === "characters" && (
            <div className="flex flex-col gap-8">
              {/* Происхождения */}
              {world.origins && world.origins.length > 0 && (
                <div className="flex flex-col gap-4">
                  <div className="border-b border-line pb-2">
                    <h2 className="font-heading text-2xl font-semibold text-ink">
                      {world.is_base ? "Базовые народы и расы" : "Происхождения и народы мира"}
                    </h2>
                    <p className="text-xs text-muted font-ui mt-0.5">
                      {world.is_base
                        ? "Базовые расы классического фэнтези для создания персонажа"
                        : "Кем начинает герой в этом сеттинге вместо стандартных рас"}
                    </p>
                  </div>

                  <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                    {world.origins.map((o) => (
                      <div
                        key={o.id}
                        className="card p-5 border-line bg-surface flex flex-col justify-between gap-3"
                      >
                        <div>
                          <div className="flex items-center justify-between gap-2 mb-1">
                            {o.badge ? (
                              <span className="font-mono text-[11px] text-copper-hi uppercase">
                                {o.badge}
                              </span>
                            ) : (
                              <span className="font-mono text-[11px] text-muted uppercase">
                                {world.is_base ? "Раса" : "Происхождение"}
                              </span>
                            )}
                            {o.size_display && (
                              <span className="rounded bg-raised px-1.5 py-0.5 font-mono text-[10px] text-muted">
                                {o.size_display}
                              </span>
                            )}
                          </div>

                          <h3 className="font-heading text-xl font-semibold text-ink">
                            {o.name}
                          </h3>
                          {o.epithet && (
                            <div className="font-serif italic text-xs text-muted mb-2">
                              {o.epithet}
                            </div>
                          )}

                          {(o.formatted_bonuses || o.speed_display) && (
                            <div className="my-2 flex flex-wrap gap-1.5">
                              {o.formatted_bonuses && (
                                <span className="rounded bg-accent/10 border border-accent/20 px-2 py-0.5 text-[11px] font-mono text-accent">
                                  {o.formatted_bonuses}
                                </span>
                              )}
                              {o.speed_display && (
                                <span className="rounded bg-raised border border-line px-2 py-0.5 text-[11px] font-mono text-muted">
                                  Скорость {o.speed_display}
                                </span>
                              )}
                            </div>
                          )}

                          <p className="font-narration text-sm text-ink-2 leading-relaxed">
                            {o.description || o.summary}
                          </p>

                          {o.highlights && o.highlights.length > 0 && (
                            <div className="mt-3 flex flex-col gap-1 border-t border-line-soft pt-2.5">
                              <span className="font-mono text-[10px] uppercase text-muted">
                                Особенности народа
                              </span>
                              {o.highlights.map((hl, idx) => (
                                <div key={idx} className="text-[11px] text-ink-2 flex items-start gap-1.5">
                                  <span className="text-accent">•</span>
                                  <span>{hl}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {o.features && o.features.length > 0 && (
                            <div className="mt-3 flex flex-col gap-2 border-t border-line-soft pt-2.5">
                              <span className="font-mono text-[10px] uppercase text-muted">
                                Черты происхождения
                              </span>
                              {o.features.map((feat, idx) => (
                                <div key={idx} className="text-xs">
                                  <span className="font-semibold text-ink">{feat.name}</span>
                                  {feat.description && (
                                    <span className="text-muted text-[11px] block mt-0.5 leading-relaxed">
                                      {feat.description}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Классы */}
              {world.classes && world.classes.length > 0 && (
                <div className="flex flex-col gap-4">
                  <div className="border-b border-line pb-2">
                    <h2 className="font-heading text-2xl font-semibold text-ink">
                      Классы и специализации
                    </h2>
                    <p className="text-xs text-muted font-ui mt-0.5">
                      Сеттинговая подача и доступные архетипы для приключенцев
                    </p>
                  </div>

                  <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                    {world.classes.map((c) => (
                      <div
                        key={c.id}
                        className="card p-5 border-line bg-surface flex flex-col justify-between gap-3"
                      >
                        <div>
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="font-mono text-[11px] text-copper-hi uppercase">
                              {c.badge || (c.hit_die ? `Кость хитов: ${c.hit_die}` : "Класс")}
                            </span>
                            {c.hit_die && (
                              <span className="rounded bg-raised px-1.5 py-0.5 font-mono text-[10px] text-muted">
                                {c.hit_die}
                              </span>
                            )}
                          </div>
                          <h3 className="font-heading text-xl font-semibold text-ink">
                            {c.name}
                          </h3>
                          {c.epithet && (
                            <div className="font-serif italic text-xs text-muted mb-2">
                              {c.epithet}
                            </div>
                          )}
                          <p className="font-narration text-sm text-ink-2 leading-relaxed">
                            {c.description || c.summary}
                          </p>

                          {c.highlights && c.highlights.length > 0 && (
                            <div className="mt-3 flex flex-col gap-1 border-t border-line-soft pt-2.5">
                              <span className="font-mono text-[10px] uppercase text-muted">
                                Ключевые особенности
                              </span>
                              {c.highlights.map((hl, idx) => (
                                <div key={idx} className="text-[11px] text-ink-2 flex items-start gap-1.5">
                                  <span className="text-accent">•</span>
                                  <span>{hl}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {c.subclasses && c.subclasses.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1 border-t border-line-soft pt-2">
                              {c.subclasses.map((sc) => (
                                <span
                                  key={sc.id}
                                  className="rounded bg-raised px-2 py-0.5 text-[10px] font-mono text-muted border border-line/60"
                                  title={sc.summary}
                                >
                                  {sc.name}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Вкладка 5: Шкалы и механики */}
          {activeTab === "mechanics" && (
            <div className="flex flex-col gap-8">
              {/* Часы мира */}
              {world.clocks && world.clocks.length > 0 && (
                <div className="flex flex-col gap-4">
                  <div className="border-b border-line pb-2">
                    <h2 className="font-heading text-2xl font-semibold text-ink">
                      Часы мира (Глобальные трекеры)
                    </h2>
                    <p className="text-xs text-muted font-ui mt-0.5">
                      Счётчики последствий, которые меняются от действий игроков и решений мастера
                    </p>
                  </div>

                  <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                    {world.clocks.map((cl) => (
                      <div
                        key={cl.id}
                        className="card p-5 border-line bg-surface flex flex-col justify-between gap-3"
                      >
                        <div>
                          <div className="flex items-center justify-between text-xs font-mono text-copper-hi mb-1">
                            <span>{cl.scope === "campaign" ? "Кампания" : "Мир"}</span>
                            <span>
                              Шкала: {cl.min}–{cl.max}
                            </span>
                          </div>
                          <h3 className="font-heading text-xl font-semibold text-ink">
                            {cl.name}
                          </h3>
                          <p className="font-narration text-sm text-ink-2 leading-relaxed mt-1">
                            {cl.description}
                          </p>

                          {cl.moves_up && cl.moves_up.length > 0 && (
                            <div className="mt-3 rounded bg-bad/5 border border-bad/20 p-2 text-xs">
                              <span className="font-mono text-[10px] uppercase text-bad font-semibold">
                                Растёт от:
                              </span>
                              <div className="text-[11px] text-ink-2 mt-0.5">
                                {cl.moves_up.slice(0, 3).join(", ")}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Уникальные шкалы героя */}
              {world.scales && world.scales.length > 0 && (
                <div className="flex flex-col gap-4">
                  <div className="border-b border-line pb-2">
                    <h2 className="font-heading text-2xl font-semibold text-ink">
                      Сеттинговые шкалы персонажей
                    </h2>
                    <p className="text-xs text-muted font-ui mt-0.5">
                      Особые ресурсы, скверна, перемена и последствия контактов с чужеродным
                    </p>
                  </div>

                  <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                    {world.scales.map((sc) => (
                      <div
                        key={sc.id}
                        className="card p-5 border-line bg-surface flex flex-col justify-between gap-3"
                      >
                        <div>
                          <div className="flex items-center justify-between text-xs font-mono text-patina-hi mb-1">
                            <span>Тип: {sc.widget_type || "число"}</span>
                            {sc.max !== undefined && sc.max !== null && (
                              <span>
                                {sc.min ?? 0}–{sc.max}
                              </span>
                            )}
                          </div>
                          <h3 className="font-heading text-xl font-semibold text-ink">
                            {sc.name}
                          </h3>
                          <p className="font-narration text-sm text-ink-2 leading-relaxed mt-1">
                            {sc.description}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Вкладка 6: Бестиарий */}
          {activeTab === "bestiary" && (
            <div className="flex flex-col gap-4">
              <div className="border-b border-line pb-2 flex items-center justify-between">
                <div>
                  <h2 className="font-heading text-2xl font-semibold text-ink">
                    Бестиарий и порождения
                  </h2>
                  <p className="text-xs text-muted font-ui mt-0.5">
                    Характерные чудовища, выводки и опасности, населяющие этот мир
                  </p>
                </div>
                {world.counts?.creature_template && (
                  <span className="font-mono text-xs text-muted bg-raised px-2.5 py-1 rounded border border-line">
                    Всего существ в базе: {world.counts.creature_template}
                  </span>
                )}
              </div>

              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                {world.bestiary.map((b) => (
                  <article
                    key={b.id}
                    className="card p-5 border-line bg-surface flex flex-col justify-between gap-3"
                  >
                    <div>
                      <div className="flex items-center justify-between text-xs font-mono text-muted mb-1">
                        <span className="text-copper-hi uppercase">{b.kind || "Существо"}</span>
                        {b.cr !== undefined && b.cr !== null && <span>Опасность: CR {b.cr}</span>}
                      </div>
                      <h3 className="font-heading text-lg font-semibold text-ink">
                        {b.name}
                      </h3>
                      {b.description && (
                        <p className="font-narration text-sm text-ink-2 leading-relaxed mt-1">
                          {b.description}
                        </p>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
