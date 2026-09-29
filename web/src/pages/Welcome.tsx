import { ThemeToggle } from "../components/Header";
import AuthForm from "../components/AuthForm";

export default function Welcome() {
  return (
    <main className="relative mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-4 py-12">
      {/* Background radial glow */}
      <div className="pointer-events-none absolute left-1/2 top-1/3 -translate-x-1/2 -translate-y-1/2 h-80 w-80 rounded-full bg-accent/5 blur-3xl" />

      {/* Top Header branding */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <svg
            width="36"
            height="36"
            viewBox="0 0 34 34"
            fill="none"
            stroke="var(--tf-accent)"
            strokeWidth="1.6"
            aria-hidden="true"
          >
            <circle cx="17" cy="17" r="15" />
            <circle cx="17" cy="17" r="9" strokeDasharray="2 3" />
            <path d="M6 21 C 11 14, 22 13, 28 17 C 24 20, 14 23, 6 21 Z" />
            <circle cx="24" cy="17.2" r="1.2" fill="var(--tf-accent)" />
          </svg>
          <span className="font-heading text-2xl font-bold tracking-[0.16em] text-ink">
            TALEFORGE
          </span>
        </div>
        <ThemeToggle />
      </div>

      {/* Narrative Intro */}
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-accent mb-1.5 font-semibold">
          Судовой журнал экспедиций
        </div>
        <p className="font-narration text-lg leading-relaxed text-ink-2">
          Текстовые ролевые приключения по канонам D&amp;D. Искусственный интеллект ведёт историю и ставит вызовы,
          а вы управляете судьбой своего отряда.
        </p>
      </div>

      {/* Auth Card */}
      <AuthForm />

      <footer className="text-center font-mono text-xs text-faint">
        TaleForge Platform · Версия судовой системы 2026
      </footer>
    </main>
  );
}
