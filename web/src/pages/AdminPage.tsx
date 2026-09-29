import { Link, useSearchParams } from "react-router-dom";
import AudioSection from "../admin/AudioSection";
import PacksSection from "../admin/PacksSection";
import SpendSection from "../admin/SpendSection";
import VoiceSection from "../admin/VoiceSection";
import Header from "../components/Header";
import ModelsSection from "../profile/ModelsSection";
import UsersSection from "../profile/UsersSection";
import { useSession } from "../stores/session";

type Tab = "packs" | "models" | "voice" | "audio" | "spend" | "users";

interface TabItem {
  id: Tab;
  label: string;
  badge?: string;
  icon: (active: boolean) => React.ReactNode;
}

/** Админка: пакеты сеттинга, модели ИИ, расходы; пользователи и роли — у Super Admin. */
export default function AdminPage() {
  const user = useSession((s) => s.user)!;
  const [params, setParams] = useSearchParams();
  const superAdmin = user.platform_role === "super_admin";

  const allTabs: TabItem[] = [
    {
      id: "packs",
      label: "Пакеты сеттинга",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
          <path d="m3.3 7 8.7 5 8.7-5" />
          <path d="M12 22V12" />
        </svg>
      ),
    },
    {
      id: "models",
      label: "Модели ИИ",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 2a4 4 0 0 0-4 4v1H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z" />
          <circle cx="9" cy="13" r="1.5" fill={active ? "var(--tf-accent)" : "currentColor"} />
          <circle cx="15" cy="13" r="1.5" fill={active ? "var(--tf-accent)" : "currentColor"} />
          <path d="M10 17h4" />
        </svg>
      ),
    },
    {
      id: "voice",
      label: "Голос",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 10a7 7 0 0 0 14 0" />
          <path d="M12 17v5" />
        </svg>
      ),
    },
    {
      id: "audio",
      label: "Звук",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M9 18V5l12-2v13" />
          <circle cx="6" cy="18" r="3" />
          <circle cx="18" cy="16" r="3" />
        </svg>
      ),
    },
    {
      id: "spend",
      label: "Расходы и лимиты",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 3v18h18" />
          <path d="m19 9-5 5-4-4-3 3" />
        </svg>
      ),
    },
    ...(superAdmin
      ? ([
          {
            id: "users",
            label: "Пользователи",
            badge: "SUPER",
            icon: (active: boolean) => (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke={active ? "var(--tf-accent)" : "currentColor"}
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            ),
          },
        ] as TabItem[])
      : []),
  ];

  const asked = params.get("tab") as Tab | null;
  const tab: Tab = allTabs.some((t) => t.id === asked) ? asked! : "packs";

  return (
    <>
      <Header>
        <Link
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          to="/"
          aria-label="К столам кампаний"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>
      </Header>

      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          {/* Subtle brass background accent */}
          <div className="pointer-events-none absolute -right-8 -top-8 h-40 w-40 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Терминал надзора и конфигурации</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                Управление системой
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Централизованный пульт: миры, нейросетевые модели, лимиты расходов и экипаж платформы.
              </p>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-center">
              <span
                className={`font-mono text-xs px-3 py-1 rounded-full border tracking-wide uppercase ${
                  superAdmin
                    ? "border-accent bg-accent/10 text-accent font-semibold"
                    : "border-patina bg-patina/10 text-patina font-semibold"
                }`}
              >
                {superAdmin ? "Суперадминистратор" : "Администратор"}
              </span>
            </div>
          </div>
        </div>

        {user.platform_role === "player" ? (
          <div className="card border-bad/40 bg-bad/5 p-6 text-center">
            <h2 className="font-heading text-xl font-bold text-bad">Доступ ограничен</h2>
            <p className="mt-2 text-sm text-muted">
              Панель управления доступна только администраторам и мастерскому составу.
            </p>
            <div className="mt-4">
              <Link to="/" className="btn btn-outline-copper">
                Вернуться к моим играм
              </Link>
            </div>
          </div>
        ) : (
          <>
            {/* Custom Tab Navigation with horizontal scrolling on mobile */}
            <nav
              className="flex items-center gap-2 border-b border-line pb-px overflow-x-auto no-scrollbar"
              role="tablist"
              aria-label="Разделы панели управления"
            >
              {allTabs.map((t) => {
                const isActive = tab === t.id;
                return (
                  <button
                    key={t.id}
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setParams({ tab: t.id }, { replace: true })}
                    className={`group flex items-center gap-2 whitespace-nowrap rounded-t-[10px] border-b-2 px-3.5 py-2.5 text-xs sm:text-sm font-medium transition ${
                      isActive
                        ? "border-accent bg-raised/80 text-ink shadow-sm"
                        : "border-transparent text-muted hover:bg-raised/40 hover:text-ink"
                    }`}
                  >
                    <span>{t.icon(isActive)}</span>
                    <span className={isActive ? "text-accent font-semibold" : ""}>{t.label}</span>
                    {t.badge && (
                      <span className="rounded bg-accent/20 px-1.5 py-0.2 text-[10px] font-mono font-semibold text-accent">
                        {t.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>

            {/* Tab Contents */}
            <div className="flex flex-col gap-6">
              {tab === "packs" && <PacksSection />}
              {tab === "models" && <ModelsSection superAdmin={superAdmin} />}
              {tab === "voice" && <VoiceSection />}
              {tab === "audio" && <AudioSection />}
              {tab === "spend" && <SpendSection />}
              {tab === "users" && superAdmin && <UsersSection me={user} />}
            </div>
          </>
        )}
      </main>
    </>
  );
}
