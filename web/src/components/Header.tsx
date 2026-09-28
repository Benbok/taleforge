import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../stores/session";

export function ThemeToggle() {
  const { mode, toggleMode } = useSession();
  return (
    <button className="btn px-2 py-1" onClick={toggleMode} title="Сменить тему" aria-label="Сменить тему">
      {mode === "dark" ? "☾" : "☀"}
    </button>
  );
}

export default function Header({ children }: { children?: ReactNode }) {
  const { user, signOut } = useSession();
  const navigate = useNavigate();
  return (
    <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3">
      <Link to="/" className="font-heading text-lg font-semibold text-ink no-underline">
        Taleforge
      </Link>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      <ThemeToggle />
      {user && (
        <>
          <a className="hidden text-muted hover:text-ink sm:inline" href="/legacy" title="Профиль, герои и настройки — пока в прежнем клиенте">
            {user.name}
          </a>
          <button
            className="btn px-2 py-1"
            onClick={() => {
              signOut();
              navigate("/");
            }}
          >
            Выйти
          </button>
        </>
      )}
    </header>
  );
}
