import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ActionButton from "../components/ActionButton";
import { Field, Segmented } from "../components/Form";
import BriefForm from "./BriefForm";
import { api } from "../lib/api";
import {
  cleanBrief,
  DIFFICULTY_RU,
  splitThemes,
  type Brief,
  type CampaignOptions,
  type Room,
} from "../lib/campaign";

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
    if (limit != null && (!Number.isFinite(limit) || limit < 0)) {
      throw new Error("Лимит расходов — число в долларах, например 5");
    }
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
    <div className="flex flex-col gap-6">
      {/* General Settings */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-5">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Основные параметры стола</h2>
          <p className="text-xs text-muted">Видимые параметры, темп боевых раундов и лимиты расходов</p>
        </div>

        <Field label="Название кампании">
          <input
            className="field font-heading text-lg"
            maxLength={128}
            value={f.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>

        <Field label="Публичная вводная (афиша)" hint="Её видят игроки при входе по ссылке-приглашению и в лобби стола.">
          <textarea
            className="field min-h-24 text-sm"
            maxLength={10000}
            value={f.public_intro}
            onChange={(e) => set({ public_intro: e.target.value })}
          />
        </Field>

        <Field label="Сложность вызовов">
          <Segmented
            label="Сложность"
            value={f.difficulty}
            options={Object.entries(DIFFICULTY_RU)}
            onChange={(difficulty) => set({ difficulty })}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Время на ход в бою (сек)" hint="От 30 до 300 секунд.">
            <input
              className="field font-mono text-sm"
              type="number"
              min={30}
              max={300}
              value={f.turn_timeout_sec}
              onChange={(e) => set({ turn_timeout_sec: Number(e.target.value) })}
            />
          </Field>

          <Field label="Окно сбора реплик (сек)" hint="Пауза перед ответом мастера, 0 — мгновенно.">
            <input
              className="field font-mono text-sm"
              type="number"
              min={0}
              max={300}
              value={f.collect_window_sec}
              onChange={(e) => set({ collect_window_sec: Number(e.target.value) })}
            />
          </Field>

          <Field label="Лимит расходов ($ USD)" hint="Пусто — без ограничения.">
            <input
              className="field font-mono text-sm"
              inputMode="decimal"
              placeholder="например: 10"
              value={f.spend_limit_usd}
              onChange={(e) => set({ spend_limit_usd: e.target.value })}
            />
          </Field>
        </div>

        <Field label="Запретные темы" hint="Укажите через запятую: мастер гарантированно не коснётся этих тем.">
          <input
            className="field text-sm"
            value={f.excluded}
            onChange={(e) => set({ excluded: e.target.value })}
          />
        </Field>
      </section>

      {/* Brief Form */}
      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <div className="border-b border-line pb-3">
          <h2 className="font-heading text-xl font-bold text-ink">Анкета приключения и ожидания игроков</h2>
          <p className="text-xs text-muted">
            Настройки влияют на последующие редакции сюжета и фокус повествования мастера
          </p>
        </div>

        {opts.data ? (
          <BriefForm brief={brief} opts={opts.data.brief} onChange={setBrief} />
        ) : (
          <p className="text-muted font-mono text-xs">Загрузка опций анкеты…</p>
        )}
      </section>

      {/* Save Button */}
      <div>
        <ActionButton
          primary
          className="font-mono text-xs tracking-wider"
          run={save}
          done="Настройки стола успешно сохранены"
        >
          СОХРАНИТЬ НАСТРОЙКИ СТОЛА
        </ActionButton>
      </div>

      {/* Danger Zone */}
      <section className="card p-5 sm:p-6 border border-bad/50 bg-bad/5 flex flex-col items-start gap-3">
        <div>
          <h2 className="font-heading text-xl font-bold text-bad">Опасная зона · Удаление кампании</h2>
          <p className="mt-1 text-xs sm:text-sm text-muted">
            Безвозвратно удаляет журнал чата, сюжетную арку и прогресс за столом.
            Персонажи игроков в их профилях сохранятся.
          </p>
        </div>

        <ActionButton
          danger
          className="font-mono text-xs"
          confirm={`Вы уверены, что хотите удалить кампанию «${room.name}» безвозвратно?`}
          run={async () => {
            await api(`/api/campaigns/${room.id}`, { method: "DELETE" });
            navigate("/", { replace: true });
          }}
          done="Кампания удалена"
        >
          УДАЛИТЬ КАМПАНИЮ НАВСЕГДА
        </ActionButton>
      </section>
    </div>
  );
}
