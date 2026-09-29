import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Tabs } from "../components/Form";
import Header from "../components/Header";
import MasterTab from "../cabinet/MasterTab";
import PlayersTab from "../cabinet/PlayersTab";
import PlotTab from "../cabinet/PlotTab";
import SettingsTab from "../cabinet/SettingsTab";
import { api } from "../lib/api";
import type { Room } from "../lib/campaign";

type Tab = "plot" | "players" | "master" | "settings";

/** Кабинет кампании: владельцу — всё, мастеру-человеку — сюжет и проверка героев. Вкладка — в адресе, чтобы её
 *  можно было открыть ссылкой и не терять при обновлении. */
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
  const tabs: [Tab, string][] = [
    ["plot", "Сюжет"],
    ["players", "Игроки"],
    ...(r?.is_owner && aiMaster ? ([["master", "ИИ-мастер"]] as [Tab, string][]) : []),
    ...(r?.is_owner ? ([["settings", "Настройки"]] as [Tab, string][]) : []),
  ];
  const asked = params.get("tab") as Tab | null;
  const tab = tabs.find(([t]) => t === asked)?.[0] ?? "plot";

  let body;
  if (room.isError) body = <p className="text-bad">Не удалось открыть кампанию: {(room.error as Error).message}</p>;
  else if (!r) body = <p className="text-muted">Загружаем…</p>;
  else if (!r.is_owner && r.my_role !== "master")
    body = <p className="card p-5">Кабинет открыт владельцу кампании и мастеру.</p>;
  else
    body = (
      <>
        <Tabs tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t }, { replace: true })} />
        {tab === "plot" && <PlotTab campaignId={id} />}
        {tab === "players" && <PlayersTab room={r} onRoom={setRoom} />}
        {tab === "master" && <MasterTab campaignId={id} />}
        {tab === "settings" && <SettingsTab key={r.id} room={r} onRoom={setRoom} />}
      </>
    );

  return (
    <>
      <Header>
        <Link className="btn px-3 py-1" to="/" aria-label="К кампаниям">
          ←<span className="hidden sm:inline"> Кампании</span>
        </Link>
        {r && (
          <Link className="btn btn-primary ml-auto px-3 py-1" to={`/c/${id}`}>
            К столу
          </Link>
        )}
      </Header>
      <main className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6">
        <h1 className="truncate text-2xl font-semibold">{r?.name ?? "Кабинет"}</h1>
        {body}
      </main>
    </>
  );
}
