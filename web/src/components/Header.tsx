import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../stores/session";


export function ThemeToggle() {
  const { mode, toggleMode } = useSession();
  return (
    <button
      className="btn h-9 w-9 p-0 rounded-[10px] border-line text-muted hover:text-ink hover:border-accent"
      onClick={toggleMode}
      title="Сменить тему"
      aria-label="Сменить тему"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        {mode === "dark" ? (
          <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
        ) : (
          <>
            <circle cx="12" cy="12" r="5" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </>
        )}
      </svg>
    </button>
  );
}

interface HeaderProps {
  children?: ReactNode;
  activeTab?: "tables" | "heroes" | "worlds";
  onTabChange?: (tab: "tables" | "heroes" | "worlds") => void;
  onlineCount?: number;
}

export default function Header({ children, activeTab, onTabChange, onlineCount }: HeaderProps) {
  const { user, signOut } = useSession();
  const navigate = useNavigate();

  const initial = user?.name ? user.name.charAt(0).toUpperCase() : "U";

  return (
    <header className="sticky top-0 z-40 flex h-[72px] items-center gap-6 border-b border-line bg-raised px-4 md:px-8">
      <Link to="/" className="flex items-center gap-3 text-ink no-underline group">
        <svg
          width="32"
          height="32"
          viewBox="0 0 34 34"
          fill="none"
          stroke="var(--tf-accent)"
          strokeWidth="1.6"
          aria-hidden="true"
          className="transition-transform group-hover:rotate-45"
        >
          <circle cx="17" cy="17" r="15" />
          <circle cx="17" cy="17" r="9" strokeDasharray="2 3" />
          <path d="M6 21 C 11 14, 22 13, 28 17 C 24 20, 14 23, 6 21 Z" />
          <circle cx="24" cy="17.2" r="1.2" fill="var(--tf-accent)" />
        </svg>
        <span className="font-heading text-2xl font-bold tracking-[0.14em] text-ink">
          TALEFORGE
        </span>
      </Link>

      {onTabChange && (
        <nav className="hidden md:flex items-center gap-6 text-sm ml-4 font-ui">
          <button
            type="button"
            onClick={() => onTabChange("tables")}
            className={`h-[72px] px-1 transition border-b-2 font-medium ${
              activeTab === "tables"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Столы
          </button>
          <button
            type="button"
            onClick={() => onTabChange("heroes")}
            className={`h-[72px] px-1 transition border-b-2 font-medium ${
              activeTab === "heroes"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Мои герои
          </button>
          <button
            type="button"
            onClick={() => onTabChange("worlds")}
            className={`h-[72px] px-1 transition border-b-2 font-medium ${
              activeTab === "worlds"
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            Миры
          </button>
        </nav>
      )}

      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>

      {user && (
        <div className="hidden lg:flex items-center gap-2 font-mono text-[11px] tracking-[0.1em] text-patina-hi shrink-0">
          <span className="inline-block h-2 w-2 rounded-full bg-patina animate-pulse" />
          <span>СВЯЗЬ ЕСТЬ{onlineCount !== undefined ? ` · ${onlineCount} НА ЛИНИИ` : ""}</span>
        </div>
      )}

      <ThemeToggle />

      {user && (
        <div className="flex items-center gap-3 shrink-0">
          {user.platform_role !== "player" && (
            <Link
              className="hidden text-sm text-muted no-underline hover:text-ink sm:inline font-mono text-[11px] tracking-wider"
              to="/admin"
            >
              АДМИНКА
            </Link>
          )}

          <Link
            to="/profile"
            title={`Профиль: ${user.name}`}
            className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-accent bg-[#3a4c63] text-sm font-semibold text-white no-underline transition hover:scale-105"
          >
            {initial}
          </Link>

          <button
            className="btn h-9 px-3 text-xs text-muted hover:text-ink"
            onClick={() => {
              signOut();
              navigate("/");
            }}
          >
            Выйти
          </button>
        </div>
      )}
    </header>
  );
}
