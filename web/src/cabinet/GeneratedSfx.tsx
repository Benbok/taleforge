import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ActionButton from "../components/ActionButton";
import AudioPreview from "../components/AudioPreview";
import { Field } from "../components/Form";
import { api } from "../lib/api";
import type { Room } from "../lib/campaign";

interface Version {
  id: string;
  url: string;
  duration_seconds: number;
  seed: number;
  size_bytes: number;
  created_at: string;
}

interface SavedSound {
  id: string;
  title: string;
  description: string;
  pinned: boolean;
  current_asset_id: string | null;
  duration_seconds: number;
  versions: Version[];
  job: { status: string; error: string | null; elapsed_seconds: number | null } | null;
}

interface Catalog {
  enabled: boolean;
  prepared: boolean;
  sounds: SavedSound[];
}

interface Receipt { status: "queued" | "cached" | "skipped"; reason?: string }
const STATUS: Record<string, string> = {
  staged: "Ожидает обработки",
  queued: "В очереди", running: "Создаётся", ready: "Сохранён", failed: "Ошибка генерации",
};

function SoundRow({ sound, base, refresh, available }: {
  sound: SavedSound; base: string; refresh: () => Promise<unknown>; available: boolean;
}) {
  const [title, setTitle] = useState(sound.title);
  const busy = sound.job?.status === "staged" || sound.job?.status === "queued" || sound.job?.status === "running";
  const current = sound.versions.find((v) => v.id === sound.current_asset_id);
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="field flex-1 min-w-40 text-sm" aria-label={`Название ${sound.title}`}
          maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} />
        <ActionButton className="text-xs" done="Название сохранено" run={async () => {
          await api(`${base}/${sound.id}`, { method: "PATCH", body: { title: title.trim() } });
          await refresh();
        }}>Подписать</ActionButton>
        <ActionButton className="text-xs" run={async () => {
          await api(`${base}/${sound.id}`, { method: "PATCH", body: { pinned: !sound.pinned } });
          await refresh();
        }}>{sound.pinned ? "Открепить" : "Закрепить"}</ActionButton>
      </div>
      <p className="text-sm text-muted">{sound.description}</p>
      <p className="text-xs text-muted">
        {sound.duration_seconds} с · {sound.versions.length} версий
        {sound.job && ` · ${STATUS[sound.job.status] ?? sound.job.status}`}
      </p>
      {sound.job?.error && <p role="alert" className="text-xs text-bad">{sound.job.error}</p>}
      {current && <AudioPreview key={current.id} path={current.url} title={sound.title} />}
      <div className="flex flex-wrap gap-2">
        {available && !busy && <ActionButton className="text-xs" done="Новая версия поставлена в очередь" run={async () => {
          const receipt = await api<Receipt>(`${base}/${sound.id}/regenerate`, { method: "POST" });
          if (receipt.status === "skipped") throw new Error(receipt.reason);
          await refresh();
        }}>Регенерировать и сохранить</ActionButton>}
        {!busy && <ActionButton danger className="text-xs" confirm={`Удалить «${sound.title}» и все сохранённые версии?`}
          done="Звук удалён" run={async () => {
            await api(`${base}/${sound.id}`, { method: "DELETE" });
            await refresh();
          }}>Удалить</ActionButton>}
      </div>
      {sound.versions.length > 1 && <details>
        <summary className="cursor-pointer text-xs text-muted">Предыдущие версии</summary>
        <div className="mt-2 flex flex-col gap-3">
          {sound.versions.filter((v) => v.id !== sound.current_asset_id).map((v) => (
            <div key={v.id} className="flex flex-col gap-1">
              <span className="text-xs text-muted">{new Date(v.created_at).toLocaleString()} · {v.duration_seconds.toFixed(1)} с</span>
              <AudioPreview path={v.url} title={`${sound.title}, предыдущая версия`} />
            </div>
          ))}
        </div>
      </details>}
    </article>
  );
}

export default function GeneratedSfx({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  const qc = useQueryClient();
  const base = `/api/campaigns/${room.id}/sfx`;
  const queryKey = ["generated-sfx", room.id];
  const query = useQuery({ queryKey, queryFn: () => api<Catalog>(base), refetchInterval: 3000 });
  const [description, setDescription] = useState("");
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState(3);
  const refresh = () => qc.invalidateQueries({ queryKey });
  const available = !!query.data?.enabled && !!query.data?.prepared;

  return (
    <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4" aria-label="Сохранённые эффекты">
      <div className="border-b border-line pb-3">
        <h2 className="font-heading text-xl font-bold text-ink">Сохранённые звуковые эффекты</h2>
        <p className="text-xs text-muted">Мастер повторно использует эти звуки. При регенерации прежняя версия сохраняется.
          Прослушивание здесь слышите только вы.</p>
      </div>
      <ActionButton className="btn-outline-copper self-start" run={async () => onRoom(await api<Room>(`/api/campaigns/${room.id}`, {
        method: "PATCH", body: { sfx_enabled: !room.settings.sfx_enabled },
      }))}>{room.settings.sfx_enabled ? "Выключить генерацию мастером" : "Разрешить мастеру генерировать эффекты"}</ActionButton>
      {query.isPending && <p className="text-xs text-muted">Загрузка звуков…</p>}
      {query.error && <p role="alert" className="text-xs text-bad">{query.error.message}</p>}
      {query.data && !query.data.enabled && <p className="text-xs text-muted">Генерация выключена на сервере. Сохранённые звуки доступны.</p>}
      {query.data?.enabled && !query.data.prepared && <p className="text-xs text-muted">Модель готовится. Если ожидание затянулось, проверьте запуск сервиса звуков.</p>}
      {available && <div className="flex flex-col gap-3 rounded-lg border border-line p-3">
        <Field label="Название эффекта"><input className="field text-sm" maxLength={100} value={title}
          onChange={(e) => setTitle(e.target.value)} placeholder="Скрип двери" /></Field>
        <Field label="Описание звука" hint="По-английски, 8–300 символов: модель лучше понимает такие описания.">
          <textarea className="field text-sm" minLength={8} maxLength={300} value={description}
            onChange={(e) => setDescription(e.target.value)} placeholder="A heavy wooden door slowly creaks open" />
        </Field>
        <Field label="Длительность, секунды"><input className="field w-24 text-sm" type="number" min={1} max={4} step={0.5}
          value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field>
        <ActionButton className="self-start" done="Запрос принят" run={async () => {
          const receipt = await api<Receipt>(base, { method: "POST", body: {
            description, duration_seconds: duration, ...(title.trim() ? { title: title.trim() } : {}),
          } });
          if (receipt.status === "skipped") throw new Error(receipt.reason);
          setDescription(""); setTitle("");
          await refresh();
        }}>Создать и сохранить звук</ActionButton>
      </div>}
      {query.data?.sounds.length === 0 && <p className="text-xs text-muted">Сохранённых эффектов пока нет.</p>}
      {query.data?.sounds.map((sound) => <SoundRow key={sound.id} sound={sound} base={base} refresh={refresh} available={available} />)}
    </section>
  );
}
