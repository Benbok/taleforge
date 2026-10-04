import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import CustomSelect, { type SelectOption } from "../components/CustomSelect";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import { ROLE_RU } from "../lib/campaign";
import type { User } from "../lib/types";
import { toast } from "../stores/toasts";

const ROLE_OPTIONS: SelectOption[] = [
  {
    value: "super_admin",
    label: "Суперадмин",
    sublabel: "Полный доступ: настройки, роли, все кампании",
    badge: "SUPER",
    badgeTone: "accent",
  },
  {
    value: "admin",
    label: "Администратор",
    sublabel: "Управление моделями, пакетами и своими кампаниями",
    badge: "ADMIN",
    badgeTone: "patina",
  },
  {
    value: "player",
    label: "Игрок",
    sublabel: "Участие в приключениях и управление своими героями",
    badge: "PLAYER",
    badgeTone: "muted",
  },
];

const NEW_USER_ROLE_OPTIONS: SelectOption[] = [
  {
    value: "admin",
    label: "Администратор",
    sublabel: "Доступ к панели управления (модели, пакеты)",
    badge: "ADMIN",
    badgeTone: "patina",
  },
  {
    value: "player",
    label: "Игрок",
    sublabel: "Стандартный доступ к столам кампаний",
    badge: "PLAYER",
    badgeTone: "muted",
  },
];

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
      toast.ok(`${u.name}: ${ROLE_RU[role] ?? role}`);
    } catch (e) {
      toast.error(`Роль не сменилась: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      await refresh();
    }
  }

  async function deleteUser(u: User) {
    setBusy(u.id);
    try {
      await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
      toast.ok(`${u.name}: учётная запись удалена`);
    } finally {
      setBusy(null);
      await refresh();
    }
  }

  return (
    <div className="flex flex-col gap-6" aria-label="Пользователи">
      {/* Intro info box */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
              Пользователи и роли платформы
            </h2>
            <p className="mt-1 text-sm text-muted max-w-2xl">
              Управление правами доступа. Суперадминистратор может менять роли участников и регистрировать
              новых администраторов или игроков напрямую в обход открытой регистрации.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
            <span>УЧЁТНЫХ ЗАПИСЕЙ:</span>
            <span className="font-bold text-accent">{users.data?.length ?? 0}</span>
          </div>
        </div>
      </section>

      {/* Users list */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <h3 className="font-heading text-lg font-bold text-ink">
          Список зарегистрированных пользователей
        </h3>

        {users.isError && (
          <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
            Не удалось загрузить список пользователей: {(users.error as Error).message}
          </div>
        )}

        {users.isSuccess && users.data.length === 0 && (
          <p className="text-sm text-muted">Пользователи не найдены.</p>
        )}

        <div className="divide-y divide-line/60">
          {(users.data ?? []).map((u) => {
            const isMe = u.id === me.id;
            const initial = u.name ? u.name.charAt(0).toUpperCase() : "U";
            const isSuper = u.platform_role === "super_admin";
            const isAdmin = u.platform_role === "admin";

            return (
              <div
                key={u.id}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-3.5 first:pt-1 last:pb-1"
              >
                <div className="flex items-center gap-3">
                  {/* User rivet avatar */}
                  <div
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border font-mono text-sm font-bold ${
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
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink">{u.name}</span>
                      {isMe && (
                        <span className="rounded bg-raised px-1.5 py-0.5 font-mono text-[10px] text-accent font-semibold border border-line">
                          ВЫ
                        </span>
                      )}
                    </div>
                    <div className="font-mono text-xs text-muted">
                      ID: <span className="text-faint">{u.id}</span>
                    </div>
                  </div>
                </div>

                <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:self-center">
                  <CustomSelect
                    className="sm:w-64"
                    value={u.platform_role}
                    options={ROLE_OPTIONS}
                    onChange={(val) => void setRole(u, val)}
                    disabled={isMe || busy === u.id}
                    title={
                      isMe
                        ? "Свою роль изменить нельзя, чтобы система не осталась без супер-администратора"
                        : undefined
                    }
                    ariaLabel={`Роль пользователя ${u.name}`}
                    size="sm"
                  />
                  {!isMe && (
                    <ActionButton
                      danger
                      className="shrink-0 text-xs font-mono tracking-wider"
                      title={`Удалить учётную запись ${u.name}`}
                      confirm={`Удалить учётную запись «${u.name}»? Это действие нельзя отменить.`}
                      run={() => deleteUser(u)}
                    >
                      УДАЛИТЬ
                    </ActionButton>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Create User Form */}
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <h3 className="font-heading text-lg font-bold text-ink mb-1">
          Создать пользователя напрямую
        </h3>
        <p className="text-xs text-muted mb-4">
          Регистрация учётной записи с заданным логином, паролем и ролью в системе
        </p>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Имя / Логин">
            <input
              className="field"
              placeholder="например: Navigator"
              value={f.name}
              onChange={(e) => setF({ ...f, name: e.target.value })}
            />
          </Field>

          <Field label="Пароль">
            <input
              className="field font-mono text-sm"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              value={f.password}
              onChange={(e) => setF({ ...f, password: e.target.value })}
            />
          </Field>

          <Field label="Роль в системе">
            <CustomSelect
              value={f.platform_role}
              options={NEW_USER_ROLE_OPTIONS}
              onChange={(val) => setF({ ...f, platform_role: val })}
              ariaLabel="Роль нового пользователя"
            />
          </Field>
        </div>

        <div className="mt-4 flex justify-end">
          <ActionButton
            primary
            className="text-xs font-mono tracking-wider w-full sm:w-auto"
            run={async () => {
              if (!f.name.trim()) throw new Error("Укажите имя пользователя");
              if (!f.password) throw new Error("Укажите пароль");
              await api("/api/admin/users", { body: { ...f, name: f.name.trim() } });
              setF({ name: "", password: "", platform_role: f.platform_role });
              await refresh();
            }}
            done="Пользователь успешно создан"
          >
            СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ
          </ActionButton>
        </div>
      </section>
    </div>
  );
}
