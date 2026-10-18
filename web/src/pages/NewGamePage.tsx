import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Header from "../components/Header";
import { ApiError } from "../lib/api";
import { authoring, authorKeys, newRequestKey } from "../lib/authoring";

export default function NewGamePage() {
  const navigate = useNavigate();
  const library = useQuery({ queryKey: authorKeys.library, queryFn: authoring.library });
  const [versionId, setVersionId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [players, setPlayers] = useState(4);
  // Один ключ на экземпляр намерения: двойной клик и повтор после обрыва возвращают ту же игру.
  const key = useRef(newRequestKey());
  const inflight = useRef(false); // синхронный замок: второй submit в том же такте не уходит на сервер
  const launch = useMutation({
    mutationFn: (id: string) =>
      authoring.launch(id, { options: { name: name.trim(), players, master: { type: "agent" } }, request_key: key.current }),
    onSuccess: (r) => navigate(`/c/${r.campaign_id}/manage`),
    onSettled: () => {
      inflight.current = false;
    },
  });
  const versions = library.data ?? [];
  // Новая версия не заменяет выбранную: пока автор не выбрал сам, запуск недоступен.
  const chosen = versions.find((v) => v.id === versionId);
  const title = (v: (typeof versions)[number]) => `${String(v.public_summary.title ?? "Без названия")} · версия ${v.version}`;
  return (
    <>
      <Header />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 p-4">
        <h1 className="font-heading text-2xl text-ink">Новая игра из библиотеки</h1>
        {library.isSuccess && versions.length === 0 && (
          <p className="text-sm text-muted">В библиотеке пока нет опубликованных приключений. <Link to="/author">Открыть пространство автора</Link></p>
        )}
        <ul className="flex flex-col gap-2" aria-label="Опубликованные приключения">
          {versions.map((v) => (
            <li key={v.id}>
              <button type="button" className={`btn min-h-11 w-full justify-start px-3 text-left ${versionId === v.id ? "btn-primary" : ""}`} aria-pressed={versionId === v.id} onClick={() => setVersionId(v.id)}>
                {title(v)}
              </button>
              {v.public_summary.tagline ? <p className="px-1 text-sm text-muted">{String(v.public_summary.tagline)}</p> : null}
            </li>
          ))}
        </ul>
        <form
          className="flex flex-col gap-3 rounded-lg border border-line bg-raised p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!chosen || !name.trim() || inflight.current) return;
            inflight.current = true;
            launch.mutate(chosen.id);
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Название игры</span>
            <input className="min-h-11 rounded-lg border border-line bg-surface px-2" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Игроков</span>
            <input className="min-h-11 rounded-lg border border-line bg-surface px-2" type="number" min={1} max={6} value={players} onChange={(e) => setPlayers(Number(e.target.value) || 1)} />
          </label>
          {launch.error && <p className="text-sm text-warn" role="alert">{launch.error instanceof ApiError ? launch.error.message : "не удалось создать игру"}</p>}
          <button className="btn btn-primary min-h-11 self-start px-4" type="submit" disabled={!chosen || !name.trim() || launch.isPending}>Создать игру</button>
        </form>
      </main>
    </>
  );
}
