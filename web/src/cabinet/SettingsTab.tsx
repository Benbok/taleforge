import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import { Field, Segmented } from "../components/Form";
import BriefForm from "./BriefForm";
import { api } from "../lib/api";
import { cleanBrief, DIFFICULTY_RU, splitThemes, type Brief, type CampaignOptions, type Room } from "../lib/campaign";

/** Настройки кампании (только владелец): название, вводная, темп игры, анкета, удаление. */
export default function SettingsTab({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  const navigate = useNavigate();
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  const st = room.settings;
  const [f, setF] = useState({
    name: room.name,
    public_intro: room.public_intro,
    difficulty: room.difficulty,
    turn_timeout_sec: st.turn_timeout_sec ?? 300,
    collect_window_sec: st.collect_window_sec ?? 60,
    spend_limit_usd: st.spend_limit_usd == null ? "" : String(st.spend_limit_usd),
    excluded: (st.excluded_themes ?? []).join(", "),
  });
  const [brief, setBrief] = useState<Brief>(room.brief ?? {});
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));

  async function save() {
    if (!f.name.trim()) throw new Error("Название не может быть пустым");
    const limit = f.spend_limit_usd.trim() === "" ? null : Number(f.spend_limit_usd.replace(",", "."));
    if (limit != null && (!Number.isFinite(limit) || limit < 0)) throw new Error("Лимит расходов — число в долларах, например 5");
    onRoom(
      await api<Room>(`/api/campaigns/${room.id}`, {
        method: "PATCH",
        body: {
          name: f.name.trim(),
          public_intro: f.public_intro,
          difficulty: f.difficulty,
          turn_timeout_sec: f.turn_timeout_sec,
          collect_window_sec: f.collect_window_sec,
          spend_limit_usd: limit,
          excluded_themes: splitThemes(f.excluded),
          brief: cleanBrief(brief),
        },
      }),
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <section className="card flex flex-col gap-4 p-4">
        <Field label="Название">
          <input className="field" maxLength={128} value={f.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Публичная вводная" hint="Её видят игроки по приглашению и в лобби.">
          <textarea className="field min-h-24" maxLength={10000} value={f.public_intro} onChange={(e) => set({ public_intro: e.target.value })} />
        </Field>
        <Field label="Сложность">
          <Segmented label="Сложность" value={f.difficulty} options={Object.entries(DIFFICULTY_RU)} onChange={(difficulty) => set({ difficulty })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Время на ход в бою, с" hint="От 30 до 300.">
            <input className="field" type="number" min={30} max={300} value={f.turn_timeout_sec} onChange={(e) => set({ turn_timeout_sec: Number(e.target.value) })} />
          </Field>
          <Field label="Сбор реплик, с" hint="Сколько мастер ждёт остальных, прежде чем ответить. 0 — сразу.">
            <input className="field" type="number" min={0} max={300} value={f.collect_window_sec} onChange={(e) => set({ collect_window_sec: Number(e.target.value) })} />
          </Field>
          <Field label="Лимит расходов, $" hint="Пусто — без лимита.">
            <input className="field" inputMode="decimal" value={f.spend_limit_usd} onChange={(e) => set({ spend_limit_usd: e.target.value })} />
          </Field>
        </div>
        <Field label="Запретные темы" hint="Через запятую.">
          <input className="field" value={f.excluded} onChange={(e) => set({ excluded: e.target.value })} />
        </Field>
      </section>

      <section className="card flex flex-col gap-3 p-4">
        <h2 className="text-base font-semibold">Чего ждут игроки</h2>
        <p className="text-sm text-muted">Анкета влияет на новый вариант сюжета и на то, как мастер ведёт игру.</p>
        {opts.data ? <BriefForm brief={brief} opts={opts.data.brief} onChange={setBrief} /> : <p className="text-muted">Загружаем…</p>}
      </section>

      <div>
        <ActionButton primary run={save} done="Настройки сохранены">
          Сохранить настройки
        </ActionButton>
      </div>

      <section className="card flex flex-col items-start gap-2 border-bad p-4">
        <h2 className="text-base font-semibold text-bad">Удалить кампанию</h2>
        <p className="text-sm text-muted">Удаляются чат, герои кампании и сюжет. Герои в профилях игроков останутся.</p>
        <ActionButton
          danger
          confirm={`Удалить «${room.name}» безвозвратно?`}
          run={async () => {
            await api(`/api/campaigns/${room.id}`, { method: "DELETE" });
            navigate("/", { replace: true });
          }}
          done="Кампания удалена"
        >
          Удалить навсегда
        </ActionButton>
      </section>
    </div>
  );
}
