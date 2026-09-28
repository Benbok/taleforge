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
      toast.ok(mode === "login" ? `С возвращением, ${r.user.name}` : `Добро пожаловать, ${r.user.name}`);
      onDone?.(mode === "signup" && !!inviteToken);
    }
  }

  return (
    <form onSubmit={submit} className="card flex flex-col gap-3 p-4">
      <div className="flex gap-2" role="tablist">
        {(["login", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={`btn flex-1 ${mode === m ? "border-accent" : ""}`}
            onClick={() => setMode(m)}
          >
            {m === "login" ? "Вход" : "Регистрация"}
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-muted">Имя</span>
        <input className="field" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" required />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-muted">Пароль</span>
        <input
          className="field"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
        />
        {mode === "signup" && <span className="text-xs text-muted">Не короче 6 символов.</span>}
      </label>
      {error && (
        <p className="text-bad" role="alert">
          {error}
          {mode === "login" && /неверное/.test(error) ? ". Нет аккаунта? Откройте вкладку «Регистрация»." : ""}
        </p>
      )}
      <button className="btn btn-primary" disabled={busy} aria-busy={busy}>
        {busy && <Spinner />}
        {mode === "login" ? "Войти" : "Зарегистрироваться"}
      </button>
    </form>
  );
}
