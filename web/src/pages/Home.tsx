import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import CampaignCardView from "../components/CampaignCardView";
import Header from "../components/Header";
import PortraitImage from "../components/PortraitImage";
import { hue, initials } from "../components/Avatar";
import { api } from "../lib/api";
import type { LibraryHero } from "../lib/builder";
import type { CampaignCard } from "../lib/types";
import { useSession } from "../stores/session";
import { HeroesLibrarySection, WorldsSection } from "./HomeSections";

type Tab = "tables" | "heroes" | "worlds";
type Filter = "all" | "master" | "player";
const TABS: [Tab, string, string][] = [
  ["tables", "Столы", "◇"],
  ["heroes", "Мои герои", "♙"],
  ["worlds", "Миры", "◎"],
];
const isMaster = (c: CampaignCard) =>
  c.my_role === "master" || (c.is_owner && !c.my_role);

export default function Home() {
  const user = useSession((s) => s.user)!;
  const isAdmin = user.platform_role !== "player";
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const activeTab: Tab = tabParam === "heroes" || tabParam === "worlds" ? tabParam : "tables";
  const setActiveTab = (tab: Tab) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous);
    if (tab === "tables") next.delete("tab");
    else next.set("tab", tab);
    return next;
  }, { replace: true });
  const [filter, setFilter] = useState<Filter>("all");
  const cardsQuery = useQuery({
    queryKey: ["my-campaigns"],
    queryFn: () => api<CampaignCard[]>("/api/me/campaigns"),
    refetchInterval: 30000,
  });
  const heroesQuery = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryHero[]>("/api/me/characters"),
  });
  const list = cardsQuery.data ?? [];
  const heroes = heroesQuery.data ?? [];
  const filtered = list.filter(
    (c) =>
      filter === "all" ||
      (filter === "master" ? isMaster(c) : c.my_role === "player"),
  );
  const recent = [...filtered]
    .filter((c) => c.status !== "ended")
    .sort(
      (a, b) =>
        Number(b.session_live) - Number(a.session_live) ||
        Date.parse(b.last_session_at ?? b.created_at) -
          Date.parse(a.last_session_at ?? a.created_at),
    );
  const featured = recent.find(
    (c) => c.session_live || c.status === "active" || c.status === "paused",
  );
  const remaining = filtered.filter((c) => c.id !== featured?.id);
  const filters: [Filter, string, number][] = [
    ["all", "Все", list.length],
    ["master", "Я мастер", list.filter(isMaster).length],
    ["player", "Я игрок", list.filter((c) => c.my_role === "player").length],
  ];
  const online = list
    .flatMap((c) => c.party)
    .filter((p) => p.occupant_type === "human" && p.online).length;

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <Header
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onlineCount={online}
      />
      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col px-4 pb-10 pt-8 sm:px-8 lg:px-12 lg:pt-12">
        {activeTab === "tables" && (
          <>
            <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
              <div>
                <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.24em] text-copper">
                  Место, где рождаются истории
                </p>
                <h1 className="font-narration text-3xl font-semibold tracking-tight sm:text-4xl">
                  Ваши приключения
                </h1>
                <p className="mt-3 text-sm leading-relaxed text-muted">
                  Знакомые герои, неизведанные миры и истории, которые ждут
                  продолжения.
                </p>
              </div>
              {isAdmin && (
                <Link
                  to="/?tab=worlds"
                  className="btn btn-primary min-h-11 gap-2 px-5 text-sm font-semibold"
                >
                  <span aria-hidden="true">＋</span> Новое приключение
                </Link>
              )}
            </div>
            <div className="grid flex-1 items-start gap-8 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div className="min-w-0">
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line-soft pb-4">
                  <h2 className="text-sm font-semibold">
                    Ваши столы{" "}
                    <span className="ml-1 font-normal text-muted">
                      / {list.length}
                    </span>
                  </h2>
                  <div
                    aria-label="Фильтр столов"
                    className="flex flex-wrap gap-1.5"
                  >
                    {filters.map(([value, label, count]) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                        className={`min-h-10 rounded-full border px-3 text-xs transition-colors ${filter === value ? "border-accent/50 bg-accent/10 text-copper-hi" : "border-transparent text-muted hover:border-line hover:text-ink"}`}
                      >
                        {label} · {count}
                      </button>
                    ))}
                  </div>
                </div>
                {cardsQuery.isLoading && (
                  <div role="status" className="card p-8 text-muted">
                    Загружаем ваши приключения…
                  </div>
                )}
                {cardsQuery.isError && (
                  <div
                    role="alert"
                    className="card border-bad/40 p-6 text-sm text-bad"
                  >
                    Не удалось загрузить столы.{" "}
                    <button
                      type="button"
                      className="underline"
                      onClick={() => void cardsQuery.refetch()}
                    >
                      Попробовать снова
                    </button>
                  </div>
                )}
                {featured && (
                  <section aria-label="Продолжить приключение" className="mb-7">
                    <div className="mb-3 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-muted">
                      <span className="h-1.5 w-1.5 rounded-full bg-accent" />{" "}
                      История продолжается
                    </div>
                    <CampaignCardView c={featured} featured />
                  </section>
                )}
                {remaining.length > 0 && (
                  <section aria-label="Остальные столы">
                    {featured && (
                      <h2 className="mb-4 text-sm font-medium text-muted">
                        Другие приключения
                      </h2>
                    )}
                    <div className="grid gap-4 md:grid-cols-2">
                      {remaining.map((c) => (
                        <CampaignCardView key={c.id} c={c} />
                      ))}
                    </div>
                  </section>
                )}
                {cardsQuery.isSuccess && filtered.length === 0 && (
                  <section className="rounded-2xl border border-dashed border-line bg-surface/50 px-6 py-12 text-center sm:px-12">
                    <div
                      aria-hidden="true"
                      className="mb-4 font-narration text-5xl text-accent"
                    >
                      ✧
                    </div>
                    <h2 className="font-narration text-2xl font-medium">
                      {list.length
                        ? "Здесь пока нет столов"
                        : "Каждая история начинается с первого шага"}
                    </h2>
                    <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
                      {list.length
                        ? "Выберите другую роль, чтобы найти своё приключение."
                        : isAdmin
                          ? "Выберите мир, соберите отряд и начните своё приключение."
                          : "Присоединитесь к столу по приглашению ведущего. А пока можно создать героя для будущих историй."}
                    </p>
                    {list.length ? (
                      <button
                        type="button"
                        onClick={() => setFilter("all")}
                        className="btn mt-6 min-h-11 text-sm"
                      >
                        Показать все столы
                      </button>
                    ) : (
                      <Link
                        to={isAdmin ? "/?tab=worlds" : "/heroes/new"}
                        className="btn btn-primary mt-6 min-h-11 text-sm"
                      >
                        {isAdmin ? "Выбрать мир" : "Создать героя"}
                      </Link>
                    )}
                  </section>
                )}
              </div>
              <aside className="flex min-w-0 flex-col gap-7 xl:border-l xl:border-line-soft xl:pl-7">
                <section aria-label="Мои герои">
                  <div className="mb-4 flex items-center justify-between gap-2">
                    <h2 className="font-narration text-xl font-semibold">
                      Мои герои
                    </h2>
                    <button
                      type="button"
                      onClick={() => setActiveTab("heroes")}
                      className="min-h-10 text-xs text-copper-hi hover:underline"
                    >
                      Все · {heroes.length}
                    </button>
                  </div>
                  {heroesQuery.isLoading && (
                    <p role="status" className="py-3 text-sm text-muted">
                      Загружаем героев…
                    </p>
                  )}
                  {heroesQuery.isError && (
                    <p role="alert" className="py-3 text-sm text-bad">
                      Не удалось загрузить героев.{" "}
                      <button
                        type="button"
                        className="underline"
                        onClick={() => void heroesQuery.refetch()}
                      >
                        Повторить
                      </button>
                    </p>
                  )}
                  {heroesQuery.isSuccess && heroes.length === 0 && (
                    <p className="mb-4 text-sm leading-relaxed text-muted">
                      Будущие участники ваших историй. Создайте первого героя и
                      возьмите его в приключение.
                    </p>
                  )}
                  <div className="flex flex-col gap-1">
                    {heroes.slice(0, 4).map((h) => (
                      <Link
                        key={h.id}
                        to={`/heroes/${h.id}`}
                        className="flex min-w-0 items-center gap-3 rounded-xl px-2 py-3 text-ink no-underline transition hover:bg-surface-2"
                      >
                        <span
                          className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full border border-accent/50 text-sm font-medium text-white"
                          style={{ background: `hsl(${hue(h.name)} 30% 30%)` }}
                        >
                          {initials(h.name)}
                          {h.portrait_url && <span className="absolute inset-0"><PortraitImage key={h.portrait_url} url={h.portrait_url} name={h.name || "Без имени"} /></span>}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold">
                            {h.name || "Без имени"}
                          </span>
                          <span className="mt-1 block truncate text-xs text-muted">
                            {h.level} ур.
                          </span>
                        </span>
                      </Link>
                    ))}
                  </div>
                  <Link
                    to="/heroes/new"
                    className="mt-3 flex min-h-11 items-center gap-3 rounded-xl border border-dashed border-line px-3 text-sm text-copper-hi no-underline transition hover:border-accent"
                  >
                    <span aria-hidden="true" className="text-lg">
                      ＋
                    </span>{" "}
                    Новый герой
                  </Link>
                </section>
                <section className="border-t border-line-soft pt-6">
                  <span aria-hidden="true" className="text-2xl text-accent">
                    ◎
                  </span>
                  <h2 className="mt-3 font-narration text-lg font-medium">
                    За пределами знакомого
                  </h2>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    У каждого мира — своя атмосфера, история и возможности для
                    героев.
                  </p>
                  <button
                    type="button"
                    onClick={() => setActiveTab("worlds")}
                    className="mt-3 min-h-11 text-sm font-medium text-copper-hi hover:underline"
                  >
                    Открыть миры <span aria-hidden="true">→</span>
                  </button>
                </section>
              </aside>
            </div>
          </>
        )}
        {activeTab === "heroes" && (
          <>
            {heroesQuery.isLoading && <p role="status">Загружаем героев…</p>}
            {heroesQuery.isError && (
              <p role="alert" className="text-bad">
                Не удалось загрузить героев.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void heroesQuery.refetch()}
                >
                  Повторить
                </button>
              </p>
            )}
            {heroesQuery.isSuccess && <HeroesLibrarySection heroes={heroes} />}
          </>
        )}
        {activeTab === "worlds" && <WorldsSection isAdmin={isAdmin} />}
      </main>
      <footer className="border-t border-line-soft px-4 pb-24 pt-5 sm:px-8 md:pb-5 lg:px-12">
        <div className="mx-auto flex max-w-[1344px] flex-wrap items-center justify-between gap-3 text-xs text-muted">
          <p>
            <span className="font-semibold tracking-wide text-ink">
              Taleforge
            </span>
            <span className="mx-3 text-faint">·</span>Ваши миры. Ваши истории.
          </p>
          {isAdmin && (
            <Link
              to="/author"
              className="min-h-10 content-center text-muted no-underline hover:text-copper-hi"
            >
              Творческая студия <span aria-hidden="true">↗</span>
            </Link>
          )}
        </div>
      </footer>
      <nav
        aria-label="Основная навигация"
        className="fixed inset-x-0 bottom-0 z-50 flex min-h-16 items-center justify-around border-t border-line bg-raised pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {TABS.map(([tab, label, icon]) => (
          <button
            key={tab}
            type="button"
            aria-current={activeTab === tab ? "page" : undefined}
            onClick={() => setActiveTab(tab)}
            className={`flex min-h-16 flex-1 flex-col items-center justify-center gap-1 text-[11px] ${activeTab === tab ? "text-copper-hi" : "text-muted"}`}
          >
            <span aria-hidden="true" className="text-xl">
              {icon}
            </span>
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}
