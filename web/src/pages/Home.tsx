import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import CampaignCardView from "../components/CampaignCardView";
import Recap from "../components/Recap";
import Header from "../components/Header";
import LeviathanEchoArt from "../components/LeviathanEchoArt";
import Avatar, { hue, initials } from "../components/Avatar";
import { api } from "../lib/api";
import type { LibraryHero } from "../lib/builder";
import { actionOf, when } from "../lib/cards";
import type { CampaignCard } from "../lib/types";
import { useSession } from "../stores/session";

export default function Home() {
  const user = useSession((s) => s.user)!;
  const isAdmin = user.platform_role !== "player";

  const [activeTab, setActiveTab] = useState<"tables" | "heroes" | "worlds">("tables");
  const [filter, setFilter] = useState<"all" | "master" | "player">("all");

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

  // Active / featured campaign for "Вахта продолжается"
  const featured =
    list.find((c) => c.session_live) ||
    list.find((c) => c.status === "active") ||
    list[0];

  // Role filtering
  const masterCount = list.filter(
    (c) => c.my_role === "master" || (c.is_owner && !c.my_role)
  ).length;
  const playerCount = list.filter((c) => c.my_role === "player").length;

  const filteredList = list.filter((c) => {
    if (filter === "master") return c.my_role === "master" || (c.is_owner && !c.my_role);
    if (filter === "player") return c.my_role === "player";
    return true;
  });

  const onlineHeroes = list
    .flatMap((c) => c.party)
    .filter((p) => p.occupant_type === "human" && p.online).length;

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink">
      <Header
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onlineCount={onlineHeroes}
      >
        {isAdmin && (
          <Link
            className="btn btn-primary px-3 py-1.5 text-xs font-semibold shadow-sm"
            to="/new"
          >
            + Новая кампания
          </Link>
        )}
      </Header>

      {activeTab === "tables" && (
        <>
          {/* СЕКЦИЯ HERO: «ВАХТА ПРОДОЛЖАЕТСЯ» */}
          {featured ? (
            <HeroSection campaign={featured} />
          ) : (
            <EmptyHeroSection isAdmin={isAdmin} />
          )}

          {/* ОСНОВНОЙ ДАШБОРД: СТОЛЫ СЛЕВА + ГЕРОИ И ТЕЛЕГРАФ СПРАВА */}
          <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-10 px-4 py-10 md:px-12 lg:flex-row">
            {/* Левая колонка: Ваши столы */}
            <div className="flex flex-1 flex-col gap-6 min-w-0">
              <div className="flex flex-wrap items-baseline justify-between gap-4">
                <h2 className="font-heading text-3xl font-semibold text-ink">
                  Ваши столы
                </h2>
                <div className="flex items-center gap-2 text-sm font-ui">
                  <button
                    type="button"
                    onClick={() => setFilter("all")}
                    className={`h-9 rounded-full px-3.5 transition text-xs font-medium ${
                      filter === "all"
                        ? "border border-accent bg-[#231a12] text-ink"
                        : "border border-line bg-transparent text-muted hover:text-ink"
                    }`}
                  >
                    Все · {list.length}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilter("master")}
                    className={`h-9 rounded-full px-3.5 transition text-xs font-medium ${
                      filter === "master"
                        ? "border border-accent bg-[#231a12] text-ink"
                        : "border border-line bg-transparent text-muted hover:text-ink"
                    }`}
                  >
                    Я мастер · {masterCount}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilter("player")}
                    className={`h-9 rounded-full px-3.5 transition text-xs font-medium ${
                      filter === "player"
                        ? "border border-accent bg-[#231a12] text-ink"
                        : "border border-line bg-transparent text-muted hover:text-ink"
                    }`}
                  >
                    Я игрок · {playerCount}
                  </button>
                </div>
              </div>

              {cardsQuery.isLoading && (
                <div className="card p-8 text-center text-muted">
                  Загружаем столы и хроники…
                </div>
              )}

              {cardsQuery.isError && (
                <div className="card p-6 border-bad text-bad text-center">
                  Не удалось загрузить кампании: {(cardsQuery.error as Error).message}
                </div>
              )}

              <div className="grid gap-6 sm:grid-cols-1 md:grid-cols-2">
                {filteredList.map((c) => (
                  <CampaignCardView key={c.id} c={c} />
                ))}

                {/* Карточка «Заложить новую кампанию» */}
                {isAdmin && (
                  <Link
                    to="/new"
                    className="card group flex min-h-[240px] flex-col items-center justify-center gap-3 border-dashed border-[#4a4035] bg-[#131417] p-6 text-center text-ink no-underline transition hover:border-accent hover:bg-[#16171b]"
                  >
                    <div className="flex h-14 w-14 items-center justify-center rounded-full border border-dashed border-accent text-accent transition-transform group-hover:scale-110">
                      <svg
                        width="24"
                        height="24"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                    </div>
                    <span className="font-heading text-2xl font-semibold">
                      Заложить новую кампанию
                    </span>
                    <span className="font-ui text-xs text-muted">
                      Выберите мир, правила и характер мастера
                    </span>
                  </Link>
                )}
              </div>
            </div>

            {/* Правая колонка: Мои герои + Телеграф */}
            <aside className="flex w-full shrink-0 flex-col gap-8 lg:w-[360px]">
              {/* Виджет «Мои герои» */}
              <div className="flex flex-col gap-3.5">
                <div className="flex items-baseline justify-between">
                  <h3 className="font-heading text-2xl font-semibold text-ink">
                    Мои герои
                  </h3>
                  <button
                    type="button"
                    onClick={() => setActiveTab("heroes")}
                    className="text-xs font-medium text-copper hover:text-copper-hi transition"
                  >
                    Все ({heroes.length})
                  </button>
                </div>

                <div className="card divide-y divide-line-soft overflow-hidden bg-surface">
                  {heroes.slice(0, 4).map((h) => (
                    <Link
                      key={h.id}
                      to={`/heroes/${h.id}`}
                      className="flex items-center gap-3.5 px-4 py-3 text-ink no-underline transition hover:bg-raised"
                    >
                      <span
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 border-patina font-semibold text-sm"
                        style={{ background: `hsl(${hue(h.name)} 35% 32%)` }}
                      >
                        {initials(h.name)}
                      </span>
                      <div className="flex flex-1 flex-col min-w-0">
                        <span className="truncate font-semibold text-sm">
                          {h.name || "Без имени"}
                        </span>
                        <span className="truncate text-xs text-muted">
                          {[h.origin_name, h.class_name, `${h.level} ур.`]
                            .filter(Boolean)
                            .join(" · ") || "Черновик"}
                        </span>
                      </div>
                    </Link>
                  ))}

                  <Link
                    to="/heroes/new"
                    className="flex items-center gap-3.5 px-4 py-3 text-copper-hi no-underline transition hover:bg-raised font-medium text-sm"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-full border border-dashed border-[#4a4035] text-lg text-copper">
                      +
                    </span>
                    <span>Новый герой</span>
                  </Link>
                </div>
              </div>

              {/* Виджет «Телеграф» */}
              <div className="flex flex-col gap-3.5">
                <h3 className="font-heading text-2xl font-semibold text-ink">
                  Телеграф
                </h3>
                <div className="card divide-y divide-[#222328] overflow-hidden bg-[#141518] p-1 font-ui text-xs">
                  <div className="flex gap-3 px-4 py-3">
                    <span className="font-mono text-[11px] text-patina-hi shrink-0">
                      СЕЙЧАС
                    </span>
                    <span className="text-ink">
                      Связь со штабом установлена. AI-Мастер готов к сессиям.
                    </span>
                  </div>
                  {list.slice(0, 3).map((c) => (
                    <div key={c.id} className="flex gap-3 px-4 py-3">
                      <span className="font-mono text-[11px] text-muted shrink-0">
                        {c.last_session_at ? when(c.last_session_at) : "ЭПОХА"}
                      </span>
                      <span className="text-ink-2">
                        Стол «{c.name}»:{" "}
                        {c.session_live
                          ? "идёт живая сессия"
                          : c.status === "paused"
                          ? "на паузе"
                          : "в режиме готовности"}
                        .
                      </span>
                    </div>
                  ))}
                  <div className="flex gap-3 px-4 py-3">
                    <span className="font-mono text-[11px] text-muted shrink-0">
                      ВЕСТИ
                    </span>
                    <span className="text-muted">
                      Цены на хитин стабильны. Волны у Хребта под контролем Кордона.
                    </span>
                  </div>
                </div>
              </div>
            </aside>
          </main>

          {/* БЕГУЩАЯ СТРОКА СВОДКИ МИРА */}
          <div className="flex h-11 items-center gap-7 overflow-hidden whitespace-nowrap border-y border-[#2e2620] bg-ember-bg px-4 md:px-12 font-mono text-xs tracking-wider text-[#b98a5c]">
            <span className="font-bold text-copper-hi">СВОДКА ПЕПЕЛЬНОЙ ЧЕРТЫ</span>
            <span className="text-[#4a4035]">///</span>
            <span>КОРДОН: ВОЛНЫ У ХРЕБТА УЧАЩАЮТСЯ</span>
            <span className="text-[#4a4035]">///</span>
            <span>СИНДИКАТЫ КРОВИ ПОДНЯЛИ ЦЕНУ НА ЛИКВОР</span>
            <span className="text-[#4a4035]">///</span>
            <span>МАЯК В ГЛАЗНИЦЕ МОЛЧИТ ТРЕТЬИ СУТКИ</span>
            <span className="text-[#4a4035]">///</span>
            <span>СЛУШАТЕЛИ ГИЛЬДИИ ФИКСИРУЮТ НОВЫЙ ОТКЛИК РЕЗОНАНСА</span>
          </div>

          {/* ФУТЕР */}
          <footer className="flex h-16 items-center justify-between px-4 md:px-12 text-xs text-faint">
            <span>Taleforge · игры с ИИ-мастером по правилам 5e</span>
            <span className="hidden sm:inline">
              Миры: Эхо Левиафанов · Базовые правила SRD 5.1
            </span>
          </footer>
        </>
      )}

      {/* ВКЛАДКА: МОИ ГЕРОИ (ОТДЕЛЬНЫЙ ЭКРАН) */}
      {activeTab === "heroes" && (
        <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-8 px-4 py-10 md:px-12">
          <HeroesLibrarySection heroes={heroes} />
        </main>
      )}

      {/* ВКЛАДКА: МИРЫ */}
      {activeTab === "worlds" && (
        <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-8 px-4 py-10 md:px-12">
          <WorldsSection isAdmin={isAdmin} />
        </main>
      )}

      {/* МОБИЛЬНАЯ НАВИГАЦИЯ (НИЖНЯЯ ПАНЕЛЬ) */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 flex h-16 items-center justify-around border-t border-line bg-raised md:hidden">
        <button
          type="button"
          onClick={() => setActiveTab("tables")}
          className={`flex flex-col items-center gap-1 text-[11px] font-medium ${
            activeTab === "tables" ? "text-accent" : "text-muted"
          }`}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3 9h18M5 9v10M19 9v10M3 5h18" />
          </svg>
          <span>Столы</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("heroes")}
          className={`flex flex-col items-center gap-1 text-[11px] font-medium ${
            activeTab === "heroes" ? "text-accent" : "text-muted"
          }`}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6" />
          </svg>
          <span>Герои</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("worlds")}
          className={`flex flex-col items-center gap-1 text-[11px] font-medium ${
            activeTab === "worlds" ? "text-accent" : "text-muted"
          }`}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />
          </svg>
          <span>Миры</span>
        </button>
      </nav>
    </div>
  );
}

/** Секция «Вахта продолжается» для активной кампании */
function HeroSection({ campaign }: { campaign: CampaignCard }) {
  const isLive = campaign.session_live;
  const action = actionOf(campaign);
  const lastDate = when(campaign.last_session_at);

  const isEcho =
    (campaign.world ?? "").toLowerCase().includes("эхо") ||
    (campaign.world ?? "").toLowerCase().includes("левиафан");
  const worldName = (campaign.world ?? "Эхо Левиафанов").toUpperCase();

  const heroDesc = campaign.hero
    ? `вы играете за ${campaign.hero.name}${
        campaign.hero.level ? `, ${campaign.hero.level} ур.` : ""
      }`
    : campaign.my_role === "player"
    ? "герой ещё не выбран"
    : "вы ведёте этот стол";

  return (
    <section className="relative overflow-hidden border-b border-line bg-[#0d0f12] px-4 py-12 md:px-12 lg:px-20 min-h-[460px] flex items-center">
      {/* Архивная навигационная векторная графика: Левиафан, Кормчие, Монолит и глифы */}
      <LeviathanEchoArt />

      {/* Мягкая подсветка/градиент под текстом слева для идеальной читаемости */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-full lg:w-3/5 bg-gradient-to-r from-[#0d0f12] via-[#0d0f12]/85 to-transparent z-0" />

      <div className="relative z-10 flex max-w-2xl flex-col gap-4">
        <div className="font-mono text-xs tracking-[0.18em] text-patina-hi">
          {isLive ? "ВАХТА ПРОДОЛЖАЕТСЯ" : "СТОЛ ГОТОВ К ИГРЕ"} · {worldName}
        </div>

        <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-semibold leading-[1.05] tracking-tight text-ink">
          {campaign.name}
        </h1>

        {campaign.recap ? (
          <Recap
            text={campaign.recap}
            clamp="line-clamp-4"
            className="font-narration text-xl sm:text-2xl italic leading-relaxed text-ink-2 max-w-xl"
          />
        ) : (
          <p className="font-narration text-lg italic text-muted">
            Герои готовятся к выходу в туман.
          </p>
        )}

        <div className="text-xs sm:text-sm text-muted font-ui">
          {lastDate ? `Прошлая сессия ${lastDate} · ` : ""}
          {heroDesc}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-4">
          <Link
            to={action.href}
            className="btn btn-primary h-12 px-6 rounded-[10px] text-sm sm:text-base font-semibold shadow-md flex items-center gap-2.5"
          >
            <span>{action.label}</span>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Link>

          {campaign.is_owner && (
            <Link
              to={`/c/${campaign.id}/manage`}
              className="btn h-12 px-5 rounded-[10px] text-sm text-ink border-line hover:border-accent"
            >
              Кабинет стола
            </Link>
          )}

          <div className="flex items-center gap-2 ml-1" aria-label="Участники отряда">
            {campaign.party.map((m) => (
              <Avatar
                key={m.seat_id}
                name={m.hero_name ?? m.user_name}
                role={m.role}
                occupant={m.occupant_type}
                presence={
                  m.occupant_type === "human"
                    ? m.online
                      ? "online"
                      : "offline"
                    : null
                }
                size={36}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Виджет «Сила Резонанса» (только для мира Эхо Левиафанов) */}
      {isEcho && (
        <div className="hidden xl:flex absolute right-12 bottom-8 w-[280px] flex-col gap-2.5 rounded-[12px] border border-[#3a2a24] bg-ember-bg p-4 shadow-xl">
          <div className="flex justify-between font-mono text-[11px] tracking-[0.14em]">
            <span className="text-ember-hi">СИЛА РЕЗОНАНСА</span>
            <span className="text-muted">4 / 8</span>
          </div>
          <div className="grid grid-cols-8 gap-1">
            <span className="h-2 rounded-[2px] bg-ember" />
            <span className="h-2 rounded-[2px] bg-ember" />
            <span className="h-2 rounded-[2px] bg-ember" />
            <span className="h-2 rounded-[2px] bg-ember" />
            <span className="h-2 rounded-[2px] bg-[#2c2320]" />
            <span className="h-2 rounded-[2px] bg-[#2c2320]" />
            <span className="h-2 rounded-[2px] bg-[#2c2320]" />
            <span className="h-2 rounded-[2px] bg-[#2c2320]" />
          </div>
          <div className="text-xs text-ink">Волны у Хребта учащаются</div>
        </div>
      )}
    </section>
  );
}

/** Заглушка, когда нет ни одной кампании */
function EmptyHeroSection({ isAdmin }: { isAdmin: boolean }) {
  return (
    <section className="relative overflow-hidden border-b border-line bg-[#111215] px-4 py-16 text-center md:px-12">
      <div className="mx-auto flex max-w-xl flex-col items-center gap-4">
        <div className="font-mono text-xs tracking-[0.18em] text-patina-hi">
          ВАХТА ЖДЁТ ПЕРВЫЙ ОТРЯД
        </div>
        <h1 className="font-heading text-4xl font-semibold sm:text-5xl">
          Добро пожаловать в Taleforge
        </h1>
        <p className="font-narration text-lg italic text-muted max-w-md">
          «Каждая туша хранит память, а каждый кокон ждёт своего пробуждения».
        </p>
        {isAdmin ? (
          <Link to="/new" className="btn btn-primary mt-2 h-12 px-6 text-sm font-semibold">
            Заложить первую кампанию
          </Link>
        ) : (
          <p className="text-sm text-muted">
            Попросите у ведущего или владельца ссылку-приглашение за стол.
          </p>
        )}
      </div>
    </section>
  );
}

/** Полноценный экран библиотеки героев */
function HeroesLibrarySection({ heroes }: { heroes: LibraryHero[] }) {
  const qc = useQueryClient();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-line pb-4">
        <div>
          <h2 className="font-heading text-3xl font-semibold text-ink">
            Библиотека героев
          </h2>
          <p className="mt-1 text-sm text-muted font-ui">
            Персонажи профиля. Создаются заранее и могут отправляться копией в любые кампании.
          </p>
        </div>
        <Link to="/heroes/new" className="btn btn-primary px-4 py-2 text-sm font-semibold">
          + Собрать нового героя
        </Link>
      </div>

      {heroes.length === 0 ? (
        <div className="card p-12 text-center text-muted">
          <p className="text-lg">У вас пока нет созданных героев.</p>
          <p className="mt-1 text-sm">
            Соберите первого персонажа, настроив его происхождение, класс и снаряжение.
          </p>
          <Link to="/heroes/new" className="btn btn-outline-copper mt-4 inline-flex">
            Создать первого героя
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {heroes.map((h) => (
            <div
              key={h.id}
              className="card flex flex-col justify-between gap-4 p-5 transition hover:border-accent"
            >
              <div className="flex items-start gap-3.5">
                <span
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2 border-accent text-base font-semibold"
                  style={{ background: `hsl(${hue(h.name)} 35% 32%)` }}
                >
                  {initials(h.name)}
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <Link
                    to={`/heroes/${h.id}`}
                    className="truncate font-heading text-xl font-semibold text-ink no-underline hover:text-copper transition"
                  >
                    {h.name || "Без имени"}
                  </Link>
                  <span className="text-xs text-muted font-ui">
                    {[h.origin_name, h.class_name, `${h.level} уровень`]
                      .filter(Boolean)
                      .join(" · ") || "Черновик"}
                  </span>
                  {h.errors.length > 0 && (
                    <span className="mt-1 text-xs text-bad">
                      {h.errors.length} незаполненных параметров
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 border-t border-line-soft pt-3">
                <Link
                  to={`/heroes/${h.id}`}
                  className="btn h-9 px-3 text-xs font-medium"
                >
                  Редактировать
                </Link>
                <ActionButton
                  className="px-3 py-1 text-xs text-muted hover:text-bad"
                  title="Удалить героя из профиля"
                  confirm={`Удалить героя «${h.name || "без имени"}» из профиля?`}
                  run={async () => {
                    await api(`/api/me/characters/${h.id}`, { method: "DELETE" });
                    await qc.invalidateQueries({ queryKey: ["library"] });
                  }}
                  done="Герой удалён"
                >
                  Удалить
                </ActionButton>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Полноценный экран каталога миров */
function WorldsSection({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="border-b border-line pb-4">
        <h2 className="font-heading text-3xl font-semibold text-ink">
          Доступные миры и правила
        </h2>
        <p className="mt-1 text-sm text-muted font-ui">
          Пакеты сеттингов со своими шкалами, происхождениеми, бестиарием и таблицами цен.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <article className="card flex flex-col justify-between overflow-hidden border-accent bg-[#17181c] p-6">
          <div className="flex flex-col gap-3">
            <div className="font-mono text-xs tracking-widest text-copper-hi">
              ОСНОВНОЙ СЕТТИНГ · БИОПАНК / ДИЗЕЛЬПАНК
            </div>
            <h3 className="font-heading text-3xl font-semibold text-ink">
              Эхо Левиафанов
            </h3>
            <p className="font-narration text-base italic leading-relaxed text-ink-2">
              Мир титанов, павших сорок лет назад. Люди живут на остывающих телах гигантов,
              добывая ликвор и сражаясь с выводками Резонанса на Пепельной черте.
            </p>
            <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] text-muted">
              <span className="rounded-md border border-line bg-raised px-2.5 py-1">
                Шкалы: Скверна и Перемена
              </span>
              <span className="rounded-md border border-line bg-raised px-2.5 py-1">
                Уровни: 1–15
              </span>
              <span className="rounded-md border border-line bg-raised px-2.5 py-1">
                Система: SRD 5.1 Hack
              </span>
            </div>
          </div>

          <div className="mt-6 flex items-center justify-between border-t border-line-soft pt-4">
            <span className="text-xs text-patina-hi font-mono">АКТИВЕН В СИСТЕМЕ</span>
            {isAdmin && (
              <Link to="/new" className="btn btn-primary text-xs font-semibold">
                Запустить стол
              </Link>
            )}
          </div>
        </article>

        <article className="card flex flex-col justify-between overflow-hidden border-line bg-surface p-6">
          <div className="flex flex-col gap-3">
            <div className="font-mono text-xs tracking-widest text-muted">
              КЛАССИЧЕСКИЙ НАБОР ПРАВИЛ
            </div>
            <h3 className="font-heading text-3xl font-semibold text-ink">
              D&D 5e SRD 5.1
            </h3>
            <p className="font-narration text-base italic leading-relaxed text-muted">
              Базовые правила классического фэнтези от Wizards of the Coast (CC BY 4.0).
              Подходит для кастомных приключений в традиционном сеттинге меча и магии.
            </p>
            <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] text-muted">
              <span className="rounded-md border border-line bg-raised px-2.5 py-1">
                12 базовых классов
              </span>
              <span className="rounded-md border border-line bg-raised px-2.5 py-1">
                Свободный бестиарий
              </span>
            </div>
          </div>

          <div className="mt-6 flex items-center justify-between border-t border-line-soft pt-4">
            <span className="text-xs text-muted font-mono">БАЗОВЫЙ ПАКЕТ</span>
            {isAdmin && (
              <Link to="/new" className="btn text-xs">
                Запустить стол
              </Link>
            )}
          </div>
        </article>
      </div>
    </div>
  );
}
