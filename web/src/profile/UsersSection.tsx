import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { ROLE_RU } from "../lib/campaign";
import type { User } from "../lib/types";
import { toast } from "../stores/toasts";

/** Пользователи и роли (только Super Admin): завести админа или игрока без приглашения, сменить роль. */
export default function UsersSection({ me }: { me: User }) {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/api/admin/users") });
  const [f, setF] = useState({ name: "", password: "", platform_role: "admin" });
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });

  async function setRole(u: User, role: string) {
    setBusy(u.id);
    try {
      await api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { platform_role: role } });
      toast.ok(`${u.name}: ${ROLE_RU[role]}`);
    } catch (e) {
      toast.error(`Роль не сменилась: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      await refresh();
    }
  }

  return (
    <section className="card flex flex-col gap-4 p-4" aria-label="Пользователи">
      <h2 className="text-base font-semibold">Пользователи и роли</h2>
      {users.isError && <p className="text-bad">Не удалось загрузить: {(users.error as Error).message}</p>}
      <ul className="flex flex-col divide-y divide-line">
        {(users.data ?? []).map((u) => (
          <li key={u.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <span>
              {u.name}
              {u.id === me.id && <span className="text-muted"> (вы)</span>}
            </span>
            <select
              className="field w-40"
              aria-label={`Роль ${u.name}`}
              disabled={u.id === me.id || busy === u.id}
              title={u.id === me.id ? "Свою роль сменить нельзя: платформа не должна остаться без Super Admin" : undefined}
              value={u.platform_role}
              onChange={(e) => void setRole(u, e.target.value)}
            >
              {Object.entries(ROLE_RU).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Имя" className="min-w-36 flex-1">
          <input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Пароль" className="min-w-36 flex-1">
          <input className="field" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Field>
        <Field label="Роль">
          <select className="field" value={f.platform_role} onChange={(e) => setF({ ...f, platform_role: e.target.value })}>
            <option value="admin">Админ</option>
            <option value="player">Игрок</option>
          </select>
        </Field>
        <ActionButton
          primary
          run={async () => {
            await api("/api/admin/users", { body: { ...f, name: f.name.trim() } });
            setF({ name: "", password: "", platform_role: f.platform_role });
            await refresh();
          }}
          done="Пользователь создан"
        >
          Создать
        </ActionButton>
      </div>
    </section>
  );
}
