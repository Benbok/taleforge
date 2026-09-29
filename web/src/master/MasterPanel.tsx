import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import { Tabs } from "../components/Form";
import { PlotDetails, type Plot } from "../cabinet/PlotTab";
import { api } from "../lib/api";
import { useGame } from "../stores/game";
import { useSession } from "../stores/session";
import MasterLog from "./MasterLog";
import ToolForm from "./ToolForm";
import { callTool, labelOf, TOOL_RU, VALUE_RU, type MasterPanelData, type ToolSpec, type Values } from "./tools";

type Tab = "scene" | "tools" | "templates" | "secrets" | "players" | "log";
interface Open {
  tool: string;
  prefill?: Values;
  key: number;
}

/** Панель живого мастера: те же инструменты, что у ИИ-мастера, формами. Видит её только место мастера. */
export default function MasterPanel({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient();
  const admin = useSession((s) => s.user?.platform_role !== "player");
  const panel = useQuery({
    queryKey: ["master-panel", campaignId],
    queryFn: () => api<MasterPanelData>(`/api/campaigns/${campaignId}/master-panel`),
  });
  const [tab, setTab] = useState<Tab>("scene");
  const [open, setOpen] = useState<Open | null>(null);

  // сцена сменилась (кто-то вошёл, ушёл, начался бой) — списки допустимых значений тоже
  const scene = useGame((s) => s.scene);
  const heroes = useGame((s) => s.heroes);
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: ["master-panel", campaignId] });
  }, [scene, heroes, qc, campaignId]);

  const tabs: [Tab, string][] = [
    ["scene", "Сцена"],
    ["tools", "Инструменты"],
    ["templates", "Шаблоны"],
    ["secrets", "Тайны"],
    ["players", "Игроки"],
    ...(admin ? ([["log", "Журнал"]] as [Tab, string][]) : []),
  ];

  if (panel.isError) return <p className="card p-4 text-sm text-bad">Панель мастера не загрузилась: {(panel.error as Error).message}</p>;
  if (!panel.data) return <p className="card p-4 text-sm text-muted">Загружаем панель мастера…</p>;
  const data = panel.data;
  const byName = new Map(data.tools.map((t) => [t.name, t]));
  const pick = (tool: string, prefill?: Values, goTo?: Tab) => {
    if (goTo) setTab(goTo);
    setOpen({ tool, prefill, key: Date.now() });
  };
  const opened = open ? byName.get(open.tool) : undefined;
  const form = opened && (
    <div className="rounded-md border border-accent/60 p-3">
      <ToolForm key={open!.key} campaignId={campaignId} tool={opened} labels={data.labels} prefill={open!.prefill} onClose={() => setOpen(null)} />
    </div>
  );
  const group = (g: string[]) => data.tools.filter((t) => g.includes(t.group));

  return (
    <section className="card flex flex-col gap-3 p-4" aria-label="Панель мастера">
      <h2 className="text-base font-semibold">Панель мастера</h2>
      <Tabs
        compact
        tabs={tabs}
        value={tab}
        onChange={(t) => {
          setTab(t);
          setOpen(null);
        }}
      />
      {tab === "scene" && (
        <>
          <SceneNow campaignId={campaignId} />
          <ToolButtons tools={group(["scene"]).filter((t) => t.name !== "get_scene")} onPick={(t) => pick(t)} active={open?.tool} />
          {form}
        </>
      )}
      {tab === "tools" && (
        <>
          <p className="text-xs text-muted">Броски, атаки и решения по действиям игроков. Сервер проверяет каждый вызов по правилам.</p>
          <ToolButtons tools={group(["checks", "other"])} onPick={(t) => pick(t)} active={open?.tool} />
          {form}
        </>
      )}
      {tab === "templates" && (
        <Templates onUse={(tool, prefill) => pick(tool, prefill, ["spawn_entity", "create_location", "apply_hazard"].includes(tool) ? "scene" : "players")} />
      )}
      {tab === "secrets" && (
        <>
          <Secrets campaignId={campaignId} hasPlot={data.has_plot} version={panel.dataUpdatedAt} />
          {data.has_plot && <ToolButtons tools={group(["plot"]).filter((t) => t.name !== "get_plot")} onPick={(t) => pick(t)} active={open?.tool} />}
          {form}
        </>
      )}
      {tab === "players" && (
        <>
          <Players tools={group(["players"])} labels={data.labels} onPick={(t, p) => pick(t, p)} />
          {form}
        </>
      )}
      {tab === "log" && <MasterLog campaignId={campaignId} />}
    </section>
  );
}

function ToolButtons({ tools, onPick, active }: { tools: ToolSpec[]; onPick: (name: string) => void; active?: string }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {tools.map((t) => (
        <button
          key={t.name}
          className={`btn px-2 py-1 text-xs ${active === t.name ? "border-accent text-accent" : ""}`}
          aria-pressed={active === t.name}
          title={t.description}
          onClick={() => onPick(t.name)}
        >
          {TOOL_RU[t.name] ?? t.name}
        </button>
      ))}
    </div>
  );
}

/** Сцена глазами мастера: все сущности с хитами и КД. Обновляется после каждого изменения сцены. */
function SceneNow({ campaignId }: { campaignId: string }) {
  const scene = useGame((s) => s.scene);
  const q = useQuery({
    queryKey: ["master-scene", campaignId, scene],
    queryFn: async () => {
      const r = await callTool("get_scene", {});
      if (!r.ok) throw new Error(r.error ?? "сцена не загрузилась");
      // id в таблице нужны модели; человеку хватает имён
      return String(r.result?.scene ?? "").replace(/\b(?:ch|en|inv|ef)_[0-9a-f]{8,}\s*/g, "");
    },
    retry: false,
  });
  return (
    <div className="rounded-md border border-line bg-raised p-3">
      {q.isError ? (
        <p className="text-sm text-bad">{(q.error as Error).message}</p>
      ) : (
        <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed">{q.data ?? "Загружаем сцену…"}</pre>
      )}
    </div>
  );
}

const TEMPLATE_USE: Record<string, [string, string, string]> = {
  creature_template: ["spawn_entity", "creature_template_id", "Выставить"],
  item_template: ["give_item", "item_template_id", "Выдать"],
  effect_template: ["apply_effect", "effect_template_id", "Наложить"],
  hazard_template: ["apply_hazard", "hazard_template_id", "Применить"],
  location_template: ["create_location", "template_id", "Создать место"],
};

interface Found {
  id: string;
  name: string;
  description?: string;
  cr?: number | string;
  value?: number | string;
  ac?: number;
  duration?: unknown;
}

function Templates({ onUse }: { onUse: (tool: string, prefill: Values) => void }) {
  const [kind, setKind] = useState("creature_template");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ results: Found[]; note: string } | null>(null);
  const use = TEMPLATE_USE[kind];
  async function search() {
    const r = await callTool("lookup_template", { kind, query: query.trim() });
    if (!r.ok) throw new Error(r.error ?? "поиск не удался");
    setFound(r.result as unknown as { results: Found[]; note: string });
  }
  return (
    <div className="flex flex-col gap-3">
      <form
        className="flex flex-wrap items-end gap-2"
        // Enter в поле нажимает кнопку «Найти» (неявная отправка формы)
        onSubmit={(e) => e.preventDefault()}
      >
        <label className="flex flex-col gap-1 text-sm">
          Что ищем
          <select className="field" value={kind} onChange={(e) => (setKind(e.target.value), setFound(null))}>
            {Object.keys(VALUE_RU)
              .filter((k) => k.endsWith("_template") || ["dc_scale", "faction", "lore_fact", "class", "origin"].includes(k))
              .map((k) => (
                <option key={k} value={k}>
                  {VALUE_RU[k]}
                </option>
              ))}
          </select>
        </label>
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm">
          Слова
          <input className="field" value={query} placeholder="название, тег, английское имя SRD" onChange={(e) => setQuery(e.target.value)} />
        </label>
        <ActionButton run={search}>Найти</ActionButton>
      </form>
      {found && !found.results.length && <p className="text-sm text-muted">{found.note || "Ничего не найдено."}</p>}
      <ul className="flex flex-col divide-y divide-line">
        {found?.results.map((x) => (
          <li key={x.id} className="flex items-start gap-2 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <b>{x.name}</b> <span className="text-xs text-muted">{x.id}</span>
              <span className="block text-xs text-muted">
                {[x.cr != null && `ОП ${x.cr}`, x.ac != null && `КД ${x.ac}`, x.value != null && `значение ${x.value}`].filter(Boolean).join(" · ")}
              </span>
              {x.description && <span className="block text-xs">{x.description}</span>}
            </span>
            {use && (
              <button
                className="btn px-2 py-0.5 text-xs"
                onClick={() => onUse(use[0], { [use[1]]: x.id, ...(use[0] === "spawn_entity" || use[0] === "create_location" ? { name: x.name } : {}) })}
              >
                {use[2]}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Тайны: заметки мастера и каркас сюжета. И то и другое сервер отдаёт только месту мастера. */
function Secrets({ campaignId, hasPlot, version }: { campaignId: string; hasPlot: boolean; version: number }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["secrets", campaignId],
    queryFn: () => api<{ setting: Record<string, unknown>; plot: Plot }>(`/api/campaigns/${campaignId}/secrets`),
  });
  const [notes, setNotes] = useState<string | null>(null);
  // после вызова инструмента сюжета панель перечитывается, а с ней и каркас
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: ["secrets", campaignId] });
  }, [version, qc, campaignId]);

  if (q.isError) return <p className="text-sm text-bad">Тайны не загрузились: {(q.error as Error).message}</p>;
  if (!q.data) return <p className="text-sm text-muted">Загружаем…</p>;
  const saved = String(q.data.setting?.notes ?? "");
  const text = notes ?? saved;
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Заметки мастера
        <textarea className="field min-h-24" maxLength={20000} value={text} onChange={(e) => setNotes(e.target.value)} />
        <span className="text-xs text-muted">Видите только вы. Здесь удобно держать тайны, имена и планы на сессию.</span>
      </label>
      <div>
        <ActionButton
          run={async () => {
            const r = await api<{ setting: Record<string, unknown>; plot: Plot }>(`/api/campaigns/${campaignId}/secrets`, {
              method: "PUT",
              body: { setting: { ...q.data.setting, notes: text } },
            });
            qc.setQueryData(["secrets", campaignId], r);
            setNotes(null);
          }}
          done="Заметки сохранены"
        >
          {notes !== null && notes !== saved ? "Сохранить заметки" : "Сохранено"}
        </ActionButton>
      </div>
      {hasPlot && q.data.plot?.title ? (
        <PlotDetails plot={q.data.plot} open />
      ) : (
        <p className="text-sm text-muted">Каркаса сюжета нет: ведёте без него. Заказать каркас можно в кабинете, пока игра не началась.</p>
      )}
    </div>
  );
}

interface Sheet {
  name: string;
  status: string;
  ac: number;
  level: number;
  abilities: Record<string, number>;
  skills: Record<string, number>;
  attacks: { name?: string; bonus?: number; damage?: string }[];
  effects: { id: string; name: string }[];
  inventory: { id: string; name: string; qty: number; equipped: boolean }[];
}

// в какое поле подставить героя: у каждого инструмента своё
const HERO_FIELD: Record<string, string> = {
  apply_effect: "target_id",
  remove_effect: "target_id",
  rest: "character_ids",
  grant_level: "character_ids",
  learn_fact: "character_ids",
};

function Players({
  tools,
  labels,
  onPick,
}: {
  tools: ToolSpec[];
  labels: Record<string, string>;
  onPick: (tool: string, prefill: Values) => void;
}) {
  const heroes = useGame((s) => s.heroes);
  const list = Object.values(heroes).filter((h) => !h.dead && h.status !== "dead");
  const [sheet, setSheet] = useState<Record<string, Sheet>>({});
  if (!list.length) return <p className="text-sm text-muted">Героев в игре пока нет.</p>;
  const quick = tools.filter((t) => t.name !== "get_character");
  return (
    <ul className="flex flex-col gap-3">
      {list.map((h) => {
        const s = sheet[h.id];
        return (
          <li key={h.id} className="rounded-md border border-line p-3 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span>
                <b>{h.name}</b>{" "}
                <span className="text-muted">
                  {[h.class_name, h.level && `ур. ${h.level}`, h.hp != null && `хиты ${h.hp}/${h.hp_max}`].filter(Boolean).join(" · ")}
                </span>
              </span>
              <ActionButton
                className="px-2 py-0.5 text-xs"
                run={async () => {
                  const r = await callTool("get_character", { character_id: h.id });
                  if (!r.ok) throw new Error(r.error ?? "лист не загрузился");
                  setSheet((x) => ({ ...x, [h.id]: r.result as unknown as Sheet }));
                }}
              >
                {s ? "Обновить лист" : "Лист"}
              </ActionButton>
            </div>
            {s && (
              <div className="mt-2 flex flex-col gap-1 text-xs">
                <span>
                  КД {s.ac} · {s.status}
                </span>
                <span className="text-muted">
                  {Object.entries(s.abilities)
                    .map(([k, v]) => `${labelOf(labels, k)} ${v}`)
                    .join(" · ")}
                </span>
                {s.attacks?.length > 0 && <span>Атаки: {s.attacks.map((a) => a.name).join(", ")}</span>}
                {s.effects?.length > 0 && <span>Эффекты: {s.effects.map((e) => e.name).join(", ")}</span>}
                {s.inventory?.length > 0 && (
                  <span>
                    Снаряжение: {s.inventory.map((i) => `${i.name}${i.qty > 1 ? ` ×${i.qty}` : ""}${i.equipped ? " (надето)" : ""}`).join(", ")}
                  </span>
                )}
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {quick.map((t) => {
                const field = HERO_FIELD[t.name] ?? "character_id";
                return (
                  <button
                    key={t.name}
                    className="btn px-2 py-0.5 text-xs"
                    title={t.description}
                    onClick={() => onPick(t.name, { [field]: field.endsWith("_ids") ? [h.id] : h.id })}
                  >
                    {TOOL_RU[t.name] ?? t.name}
                  </button>
                );
              })}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
