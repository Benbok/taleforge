import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { ROLE_RU } from "../lib/campaign";
import type { User } from "../lib/types";
import { useSession } from "../stores/session";

export interface Profile {
  user: User;
  created_at: string;
  stats: {
    campaigns_owned: number;
    campaigns_playing: number;
    campaigns_mastering: number;
    library_characters: number;
    llm_calls?: number;
    llm_spend_usd?: number;
  };
  can_manage_models: boolean;
  can_manage_users: boolean;
}

const DATE = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });

/** Аккаунт: кто вы, сколько играете, смена имени и пароля. */
export default function AccountSection({
  profile,
  onChange,
}: {
  profile: Profile;
  onChange: () => Promise<unknown>;
}) {
  const setUser = useSession((s) => s.setUser);
  const [name, setName] = useState(profile.user.name);
  const [oldPass, setOldPass] = useState("");
  const [newPass, setNewPass] = useState("");
  const s = profile.stats;

  const isSuper = profile.user.platform_role === "super_admin";
  const isAdmin = profile.user.platform_role === "admin";
  const initial = profile.user.name ? profile.user.name.charAt(0).toUpperCase() : "U";

  const stats: [number | string, string, string][] = [
    [s.campaigns_playing, "Играет", "активных столов"],
    [s.campaigns_mastering, "Ведёт сам", "в роли мастера"],
    [s.library_characters, "Героев", "в библиотеке"],
    ...(profile.can_manage_models
      ? ([
          [s.campaigns_owned, "Кампаний", "созданных столов"],
          [`$${(s.llm_spend_usd ?? 0).toFixed(2)}`, "Расходы ИИ", `${s.llm_calls ?? 0} вызовов`],
        ] as [number | string, string, string][])
      : []),
  ];

  return (
    <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-6" aria-label="Аккаунт">
      {/* Header Info */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-line pb-4">
        <div className="flex items-center gap-3.5">
          <div
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2 font-mono text-lg font-bold ${
              isSuper
                ? "border-accent bg-accent/20 text-accent"
                : isAdmin
                  ? "border-patina bg-patina/20 text-patina-hi"
                  : "border-line bg-raised text-muted"
            }`}
          >
            {initial}
          </div>

          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="font-heading text-2xl font-bold text-ink">{profile.user.name}</h2>
              <span
                className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${
                  isSuper
                    ? "border-accent/50 bg-accent/15 text-accent"
                    : isAdmin
                      ? "border-patina/50 bg-patina/15 text-patina-hi"
                      : "border-line bg-raised text-muted"
                }`}
              >
                {ROLE_RU[profile.user.platform_role] ?? profile.user.platform_role}
              </span>
            </div>
            <p className="font-mono text-xs text-faint mt-0.5">
              В экспедиционном журнале с {DATE.format(new Date(profile.created_at))}
            </p>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div>
        <h3 className="font-mono text-[11px] font-bold text-accent uppercase tracking-wider mb-2.5">
          Сводка активности
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {stats.map(([v, label, sub]) => (
            <div
              key={label}
              className="rounded-[10px] border border-line bg-raised/50 p-3.5 flex flex-col justify-between"
            >
              <div className="font-heading text-2xl font-bold text-ink tabular-nums">{v}</div>
              <div className="mt-1">
                <div className="font-mono text-xs font-semibold text-accent">{label}</div>
                <div className="font-mono text-[10px] text-faint truncate">{sub}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Forms Grid */}
      <div className="grid gap-6 md:grid-cols-2 border-t border-line pt-5">
        {/* Name Change */}
        <div className="flex flex-col gap-3">
          <h3 className="font-heading text-base font-bold text-ink">Позывной / Имя исследователя</h3>
          <p className="text-xs text-muted">Имя отображается другим игрокам за столом и в чате сессий</p>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-2.5">
            <Field label="Имя" className="flex-1">
              <input
                className="field text-sm"
                autoComplete="username"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <ActionButton
              className="font-mono text-xs whitespace-nowrap"
              run={async () => {
                if (name.trim() === profile.user.name) throw new Error("Имя не изменилось");
                setUser(await api<User>("/api/me", { method: "PATCH", body: { name: name.trim() } }));
                await onChange();
              }}
              done="Имя сохранено"
            >
              СОХРАНИТЬ
            </ActionButton>
          </div>
        </div>

        {/* Password Change */}
        <div className="flex flex-col gap-3">
          <h3 className="font-heading text-base font-bold text-ink">Безопасность и пароль</h3>
          <p className="text-xs text-muted">Смена ключа доступа к вашей учетной записи</p>
          <div className="grid gap-2.5 sm:grid-cols-2">
            <Field label="Текущий пароль">
              <input
                className="field font-mono text-sm"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={oldPass}
                onChange={(e) => setOldPass(e.target.value)}
              />
            </Field>
            <Field label="Новый пароль" hint="Минимум 6 символов.">
              <input
                className="field font-mono text-sm"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={newPass}
                onChange={(e) => setNewPass(e.target.value)}
              />
            </Field>
          </div>
          <div>
            <ActionButton
              className="font-mono text-xs w-full sm:w-auto"
              run={async () => {
                if (newPass.length < 6) throw new Error("Новый пароль короче 6 символов");
                await api("/api/me/password", { body: { old_password: oldPass, new_password: newPass } });
                setOldPass("");
                setNewPass("");
              }}
              done="Пароль успешно обновлён"
            >
              ОБНОВИТЬ ПАРОЛЬ
            </ActionButton>
          </div>
        </div>
      </div>
    </section>
  );
}
