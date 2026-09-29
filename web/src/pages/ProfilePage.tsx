import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import Header from "../components/Header";
import { api } from "../lib/api";
import AccountSection, { type Profile } from "../profile/AccountSection";
import ModelsSection from "../profile/ModelsSection";
import PersonasSection from "../profile/PersonasSection";
import UsersSection from "../profile/UsersSection";

/** Профиль: аккаунт у всех; персоны мастера и модели ИИ — у админов; пользователи — у Super Admin.
 *  Герои профиля живут на главной, в разделе «Мои герои». */
export default function ProfilePage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/me/profile") });
  const p = profile.data;
  return (
    <>
      <Header>
        <Link className="btn px-3 py-1" to="/" aria-label="К кампаниям">
          ←<span className="hidden sm:inline"> Кампании</span>
        </Link>
      </Header>
      <main className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6">
        <h1 className="text-2xl font-semibold">Профиль</h1>
        {profile.isError && <p className="text-bad">Не удалось загрузить профиль: {(profile.error as Error).message}</p>}
        {!p && !profile.isError && <p className="text-muted">Загружаем…</p>}
        {p && (
          <>
            <AccountSection profile={p} onChange={() => profile.refetch()} />
            <p className="text-sm text-muted">
              Героев профиля можно собрать и поправить на <Link to="/">главной</Link>, в разделе «Мои герои».
            </p>
            {p.can_manage_models && <PersonasSection />}
            {p.can_manage_models && <ModelsSection superAdmin={p.user.platform_role === "super_admin"} />}
            {p.can_manage_users && <UsersSection me={p.user} />}
          </>
        )}
      </main>
    </>
  );
}
