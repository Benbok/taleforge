import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import Header from "../components/Header";
import MasterTab from "../cabinet/MasterTab";
import PlayersTab from "../cabinet/PlayersTab";
import PlotTab from "../cabinet/PlotTab";
import SettingsTab from "../cabinet/SettingsTab";
import { api } from "../lib/api";
import type { Room } from "../lib/campaign";

type Tab = "plot" | "players" | "master" | "settings";

interface TabItem {
  id: Tab;
  label: string;
  icon: (active: boolean) => React.ReactNode;
}

/** Кабинет кампании: владельцу — всё, мастеру-человеку — сюжет и проверка героев. */
export default function ManagePage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const room = useQuery({ queryKey: ["room", id], queryFn: () => api<Room>(`/api/campaigns/${id}`) });
  const r = room.data;
  const setRoom = (next: Room) => {
    qc.setQueryData(["room", id], next);
    void qc.invalidateQueries({ queryKey: ["my-campaigns"] });
  };

  const aiMaster = !!r?.seats.some((s) => s.role === "master" && s.occupant_type === "agent");

  const allTabs: TabItem[] = [
    {
      id: "plot",
      label: "Сюжетная арка",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
          <path d="M6 6h10" />
          <path d="M6 10h10" />
        </svg>
      ),
    },
    {
      id: "players",
      label: "Отряд и игроки",
      icon: (active) => (
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={active ? "var(--tf-accent)" : "currentColor"}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      ),
    },
    ...(r?.is_owner && aiMaster
      ? [
          {
            id: "master" as Tab,
            label: "ИИ-мастер",
            icon: (active: boolean) => (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke={active ? "var(--tf-accent)" : "currentColor"}
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 2a4 4 0 0 0-4 4v1H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z" />
                <circle cx="9" cy="13" r="1.5" fill={active ? "var(--tf-accent)" : "currentColor"} />
                <circle cx="15" cy="13" r="1.5" fill={active ? "var(--tf-accent)" : "currentColor"} />
              </svg>
            ),
          },
        ]
      : []),
    ...(r?.is_owner
      ? [
          {
            id: "settings" as Tab,
            label: "Настройки стола",
            icon: (active: boolean) => (
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke={active ? "var(--tf-accent)" : "currentColor"}
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1Z" />
              </svg>
            ),
          },
        ]
      : []),
  ];

  const asked = params.get("tab") as Tab | null;
  const tab: Tab = allTabs.some((t) => t.id === asked) ? asked! : "plot";

  let body;
  if (room.isError) {
    body = (
      <div className="card border-bad/40 bg-bad/5 p-5 text-sm text-bad">
        Не удалось открыть кампанию: {(room.error as Error).message}
      </div>
    );
  } else if (!r) {
    body = (
      <div className="card p-8 text-center text-muted font-mono text-sm">
        Загрузка параметров стола и кабинета…
      </div>
    );
  } else if (!r.is_owner && r.my_role !== "master") {
    body = (
      <div className="card border-bad/40 bg-bad/5 p-6 text-center">
        <h2 className="font-heading text-xl font-bold text-bad">Доступ ограничен</h2>
        <p className="mt-2 text-sm text-muted">
          Кабинет управления доступен только владельцу стола и назначенному мастеру.
        </p>
      </div>
    );
  } else {
    body = (
      <>
        {/* Navigation Tabs */}
        <nav
          className="flex items-center gap-2 border-b border-line pb-px overflow-x-auto no-scrollbar"
          role="tablist"
          aria-label="Вкладки кабинета кампании"
        >
          {allTabs.map((t) => {
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={isActive}
                onClick={() => setParams({ tab: t.id }, { replace: true })}
                className={`group flex items-center gap-2 whitespace-nowrap rounded-t-[10px] border-b-2 px-3.5 py-2.5 text-xs sm:text-sm font-medium transition ${
                  isActive
                    ? "border-accent bg-raised/80 text-ink shadow-sm"
                    : "border-transparent text-muted hover:bg-raised/40 hover:text-ink"
                }`}
              >
                <span>{t.icon(isActive)}</span>
                <span className={isActive ? "text-accent font-semibold" : ""}>{t.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab Content */}
        <div className="flex flex-col gap-6">
          {tab === "plot" && <PlotTab campaignId={id} packId={r?.pack_id} />}
          {tab === "players" && <PlayersTab room={r} onRoom={setRoom} />}
          {tab === "master" && <MasterTab campaignId={id} />}
          {tab === "settings" && <SettingsTab key={r.id} room={r} onRoom={setRoom} />}
        </div>
      </>
    );
  }

  return (
    <>
      <Header>
        <Link
          className="btn btn-outline-copper h-9 px-3.5 text-xs font-mono tracking-wider flex items-center gap-1.5"
          to="/"
          aria-label="К кампаниям"
        >
          <span>←</span>
          <span className="hidden sm:inline">К СТОЛАМ</span>
        </Link>
        {r && (
          <Link
            className="btn btn-primary ml-auto h-9 px-4 text-xs font-mono tracking-wider flex items-center gap-1.5"
            to={`/c/${id}`}
          >
            <span>К СТОЛУ</span>
            <span>→</span>
          </Link>
        )}
      </Header>

      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 md:px-8 md:py-8">
        {/* Terminal Header */}
        <div className="relative overflow-hidden rounded-[14px] border border-line bg-surface p-5 sm:p-6">
          <div className="pointer-events-none absolute -right-6 -top-6 h-36 w-36 rounded-full bg-accent/5 blur-2xl" />

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.16em] text-accent uppercase">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                <span>Кабинет ведущего · Штаб стола</span>
              </div>
              <h1 className="mt-1 font-heading text-2xl sm:text-3xl font-bold tracking-wide text-ink">
                {r?.name ?? "Кабинет кампании"}
              </h1>
              <p className="mt-1 text-xs sm:text-sm text-muted">
                Управление сюжетной аркой, составом партии, приглашениями и настройками сессии.
              </p>
            </div>

            {r && (
              <div className="flex items-center gap-2 self-start sm:self-center font-mono text-xs px-3 py-1 rounded-full border border-line bg-raised text-ink-2">
                РОЛЬ:{" "}
                <span className="font-semibold text-accent">
                  {r.is_owner ? "ВЛАДЕЛЕЦ СТОЛА" : "МАСТЕР"}
                </span>
              </div>
            )}
          </div>
        </div>

        {body}
      </main>
    </>
  );
}
