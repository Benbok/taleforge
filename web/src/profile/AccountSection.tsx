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
export default function AccountSection({ profile, onChange }: { profile: Profile; onChange: () => Promise<unknown> }) {
  const setUser = useSession((s) => s.setUser);
  const [name, setName] = useState(profile.user.name);
  const [oldPass, setOldPass] = useState("");
  const [newPass, setNewPass] = useState("");
  const s = profile.stats;
  const stats: [number | string, string][] = [
    [s.campaigns_playing, "играет"],
    [s.campaigns_mastering, "ведёт сам"],
    [s.library_characters, "героев в профиле"],
    ...(profile.can_manage_models
      ? ([
          [s.campaigns_owned, "своих кампаний"],
          [`$${(s.llm_spend_usd ?? 0).toFixed(2)}`, `на модели, ${s.llm_calls ?? 0} вызовов`],
        ] as [number | string, string][])
      : []),
  ];
  return (
    <section className="card flex flex-col gap-4 p-4" aria-label="Аккаунт">
      <div>
        <h2 className="text-xl font-semibold">
          {profile.user.name}{" "}
          <span className="rounded-full border border-line px-2 py-0.5 align-middle text-xs font-normal text-muted">
            {ROLE_RU[profile.user.platform_role]}
          </span>
        </h2>
        <p className="text-sm text-muted">С нами с {DATE.format(new Date(profile.created_at))}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {stats.map(([v, label]) => (
          <div key={label} className="rounded-md border border-line p-2">
            <div className="text-xl font-semibold">{v}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Имя" className="min-w-48 flex-1">
          <input className="field" autoComplete="username" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <ActionButton
          run={async () => {
            if (name.trim() === profile.user.name) throw new Error("Имя не изменилось");
            setUser(await api<User>("/api/me", { method: "PATCH", body: { name: name.trim() } }));
            await onChange();
          }}
          done="Имя сохранено"
        >
          Сохранить имя
        </ActionButton>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Текущий пароль" className="min-w-40 flex-1">
          <input className="field" type="password" autoComplete="current-password" value={oldPass} onChange={(e) => setOldPass(e.target.value)} />
        </Field>
        <Field label="Новый пароль" hint="Не короче 6 символов." className="min-w-40 flex-1">
          <input className="field" type="password" autoComplete="new-password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
        </Field>
        <ActionButton
          run={async () => {
            if (newPass.length < 6) throw new Error("Новый пароль короче 6 символов");
            await api("/api/me/password", { body: { old_password: oldPass, new_password: newPass } });
            setOldPass("");
            setNewPass("");
          }}
          done="Пароль изменён"
        >
          Сменить пароль
        </ActionButton>
      </div>
    </section>
  );
}
