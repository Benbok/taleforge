import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import type { User } from "../lib/types";
import { useAsync } from "../lib/useAsync";
import { useSession } from "../stores/session";
import { toast } from "../stores/toasts";
import { Spinner } from "./ActionButton";

type Mode = "login" | "signup";

/** Вход и регистрация. С приглашением регистрация идёт по ссылке и сразу занимает место в кампании. */
export default function AuthForm({
  inviteToken,
  initial = "login",
  onDone,
}: {
  inviteToken?: string;
  initial?: Mode;
  onDone?: (joinedByInvite: boolean) => void;
}) {
  const [mode, setMode] = useState<Mode>(initial);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAsync();
  const signIn = useSession((s) => s.signIn);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const url =
      mode === "login" ? "/api/auth/login" : inviteToken ? `/api/auth/register/${inviteToken}` : "/api/auth/signup";
    const r = await run(() => api<{ token: string; user: User }>(url, { body: { name: name.trim(), password } }));
    if (r) {
      signIn(r.token, r.user);
      toast.ok(mode === "login" ? `С возвращением, ${r.user.name}` : `Добро пожаловать в команду, ${r.user.name}`);
      onDone?.(mode === "signup" && !!inviteToken);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="card p-6 sm:p-7 border border-line bg-surface shadow-2xl flex flex-col gap-4 relative overflow-hidden"
    >
      {/* Decorative brass corner glow */}
      <div className="pointer-events-none absolute -right-6 -top-6 h-28 w-28 rounded-full bg-accent/10 blur-xl" />

      {/* Tabs */}
      <div className="flex rounded-[10px] bg-raised/80 p-1 border border-line" role="tablist">
        {(["login", "signup"] as const).map((m) => {
          const isActive = mode === m;
          return (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`flex-1 rounded-[8px] py-2 font-mono text-xs font-semibold tracking-wider transition uppercase ${
                isActive
                  ? "bg-surface border border-accent/40 text-accent shadow-sm"
                  : "text-muted hover:text-ink"
              }`}
              onClick={() => setMode(m)}
            >
              {m === "login" ? "Вход" : "Регистрация"}
            </button>
          );
        })}
      </div>

      <div className="flex flex-col gap-3.5 pt-1">
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-semibold text-ink text-xs uppercase tracking-wider font-mono">
            Имя исследователя
          </span>
          <input
            className="field text-sm"
            placeholder="Ваш логин или позывной"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label className="flex flex-col gap-1.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink text-xs uppercase tracking-wider font-mono">
              Пароль доступа
            </span>
            {mode === "signup" && (
              <span className="text-[11px] font-mono text-faint">не короче 6 символов</span>
            )}
          </div>
          <input
            className="field font-mono text-sm"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
      </div>

      {error && (
        <div role="alert" className="rounded-[8px] border border-bad/40 bg-bad/10 p-3 font-mono text-xs text-bad">
          {error}
          {mode === "login" && /неверное/.test(error) ? " Нет учётной записи? Переключитесь на «Регистрацию» выше." : ""}
        </div>
      )}

      <button
        type="submit"
        className="btn btn-primary font-mono text-xs tracking-wider py-2.5 mt-2"
        disabled={busy}
        aria-busy={busy}
      >
        {busy && <Spinner />}
        {mode === "login" ? "ВОЙТИ В ИГРУ →" : "ЗАРЕГИСТРИРОВАТЬСЯ →"}
      </button>
    </form>
  );
}
