import { Link, useSearchParams } from "react-router-dom";
import PacksSection from "../admin/PacksSection";
import SpendSection from "../admin/SpendSection";
import { Tabs } from "../components/Form";
import Header from "../components/Header";
import ModelsSection from "../profile/ModelsSection";
import UsersSection from "../profile/UsersSection";
import { useSession } from "../stores/session";

type Tab = "packs" | "models" | "spend" | "users";

/** Админка: пакеты сеттинга, модели ИИ, расходы; пользователи и роли — у Super Admin. */
export default function AdminPage() {
  const user = useSession((s) => s.user)!;
  const [params, setParams] = useSearchParams();
  const superAdmin = user.platform_role === "super_admin";
  const tabs: [Tab, string][] = [
    ["packs", "Пакеты"],
    ["models", "Модели ИИ"],
    ["spend", "Расходы"],
    ...(superAdmin ? ([["users", "Пользователи"]] as [Tab, string][]) : []),
  ];
  const asked = params.get("tab") as Tab | null;
  const tab: Tab = tabs.some(([t]) => t === asked) ? asked! : "packs";

  return (
    <>
      <Header>
        <Link className="btn px-3 py-1" to="/" aria-label="К кампаниям">
          ←<span className="hidden sm:inline"> Кампании</span>
        </Link>
      </Header>
      <main className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6">
        <h1 className="text-2xl font-semibold">Админка</h1>
        {user.platform_role === "player" ? (
          <p className="card p-5">Админка доступна администраторам.</p>
        ) : (
          <>
            <Tabs tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t }, { replace: true })} />
            {tab === "packs" && <PacksSection />}
            {tab === "models" && <ModelsSection superAdmin={superAdmin} />}
            {tab === "spend" && <SpendSection />}
            {tab === "users" && superAdmin && <UsersSection me={user} />}
          </>
        )}
      </main>
    </>
  );
}
