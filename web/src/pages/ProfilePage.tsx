import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import Header from "../components/Header";
import { api } from "../lib/api";
import AccountSection, { type Profile } from "../profile/AccountSection";
import PersonasSection from "../profile/PersonasSection";

/** Профиль: аккаунт у всех, персоны мастера — у админов. Модели, пакеты, расходы и пользователи — в админке. */
export default function ProfilePage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/me/profile") });
  const p = profile.data;

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

      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Личное дело исследователя · Учётные данные</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                Профиль игрока
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Управление учетной записью, безопасность, статистика походов и персоны ИИ-мастера.
              </p>
            </div>

            {p && (
              <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
                СТАТУС:{" "}
                <span className="font-semibold text-accent">
                  {p.user.platform_role === "super_admin"
                    ? "СУПЕРАДМИН"
                    : p.user.platform_role === "admin"
                      ? "АДМИНИСТРАТОР"
                      : "ИГРОК"}
                </span>
              </div>
            )}
          </div>
        </div>

        {profile.isError && (
          <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
            Не удалось загрузить данные профиля: {(profile.error as Error).message}
          </div>
        )}

        {!p && !profile.isError && (
          <div className="card p-8 text-center text-muted font-mono text-sm">
            Извлечение записей формуляра игрока…
          </div>
        )}

        {p && (
          <div className="flex flex-col gap-6">
            <AccountSection profile={p} onChange={() => profile.refetch()} />

            {/* Quick Links Card */}
            <section className="card p-5 border border-line bg-surface flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="font-heading text-base font-bold text-ink">Связанные разделы платформы</h3>
                <p className="text-xs text-muted mt-0.5">
                  Управление персонажами доступно на главной странице, системные параметры — в админке.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Link to="/" className="btn btn-outline-copper font-mono text-xs">
                  МОИ ГЕРОИ →
                </Link>
                {p.can_manage_models && (
                  <Link to="/admin" className="btn btn-primary font-mono text-xs">
                    АДМИН-ПАНЕЛЬ →
                  </Link>
                )}
              </div>
            </section>

            {/* Master Personas Section (admins only) */}
            {p.can_manage_models && <PersonasSection />}
          </div>
        )}
      </main>
    </>
  );
}
