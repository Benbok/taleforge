import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { authoring, authorKeys, newRequestKey, type StudioFields, type StudioView } from "../lib/authoring";

const groups: [keyof StudioFields, string, string][] = [
  ["premise", "Замысел", "О чём приключение и что интересно исследовать"],
  ["world", "Мир", "Места, эпоха и повседневная жизнь"],
  ["laws", "Законы мира", "Что возможно и невозможно. Мастер задаёт вопросы, а изменения сохраняете вы"],
  ["inhabitants", "Обитатели", "Народы, существа и общества"],
  ["powers", "Силы и возможности", "Как действуют магия, технологии и другие силы"],
  ["history", "История", "Прошлое мира; сведения доступны автору и мастеру"],
  ["start", "Начало приключения", "Конкретное место и ситуация первого игрового шага"],
  ["style", "Стиль", "Тон и желаемое впечатление"],
  ["public_text", "Текст для игроков", "Только этот текст и название войдут в открытое описание версии"],
  ["secret_text", "Секреты мастера", "Скрытые мотивы, тайны и будущие открытия"],
];
const inputClass = "rounded-xl border border-line bg-raised p-3 text-ink";

export default function UniversalWorldStudio({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const key = ["author", projectId, "studio"];
  const studio = useQuery({ queryKey: key, queryFn: () => authoring.getStudio(projectId) });
  const project = useQuery({ queryKey: authorKeys.project(projectId, "summary"), queryFn: () => authoring.getProject(projectId, "summary") });
  const [fields, setFields] = useState<StudioFields | null>(null);
  const [answer, setAnswer] = useState("");
  const acceptKey = useRef(newRequestKey());
  const launchKeys = useRef<Record<string, string>>({});
  useEffect(() => { if (studio.data) { setFields(studio.data.fields); acceptKey.current = newRequestKey(); } }, [studio.data?.draft_revision]); // reset only when server content changes
  const refresh = () => {
    void client.invalidateQueries({ queryKey: authorKeys.projects });
    void client.invalidateQueries({ queryKey: authorKeys.project(projectId, "summary") });
    void client.invalidateQueries({ queryKey: authorKeys.library });
  };
  const save = useMutation({ mutationFn: () => authoring.saveStudio(projectId, studio.data!.draft_revision, fields!),
    onSuccess: (view) => { client.setQueryData(key, view); refresh(); } });
  const review = useMutation({ mutationFn: (text: string) => authoring.reviewStudio(projectId, studio.data!.draft_revision, text),
    onSuccess: (result) => { client.setQueryData<StudioView>(key, previous => previous ? { ...previous, review: result } : previous); setAnswer(""); } });
  const accept = useMutation({ mutationFn: () => authoring.acceptStudio(projectId, studio.data!.draft_revision, acceptKey.current), onSuccess: refresh });
  const launch = useMutation({ mutationFn: (versionId: string) => {
    launchKeys.current[versionId] ??= newRequestKey();
    return authoring.launch(versionId, { request_key: launchKeys.current[versionId], options: { name: fields!.title, owner_plays: true, players: 1, excluded_themes: fields!.excluded_themes } });
  }, onSuccess: receipt => navigate(receipt.url) });
  const dirty = !!fields && JSON.stringify(fields) !== JSON.stringify(studio.data?.fields);
  const busy = save.isPending || review.isPending || accept.isPending || launch.isPending;
  const error = save.error || review.error || accept.error || launch.error || studio.error;
  if (!fields) return <p className="p-6" role={studio.error ? "alert" : "status"}>{studio.error ? studio.error.message : "Загрузка мира…"}</p>;
  const update = <K extends keyof StudioFields>(name: K, value: StudioFields[K]) => setFields(old => old ? { ...old, [name]: value } : old);
  const receipt = studio.data?.review;
  return <main className="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-6">
    <header><h1 className="font-heading text-3xl text-ink">Творческая студия</h1>
      <p className="mt-2 text-sm text-ink-2">Опишите мир, обсудите вопросы с мастером и примите версию для независимых приключений.</p>
      <p className="mt-2 text-sm text-muted">Редакция {studio.data?.draft_revision}{dirty ? " · есть несохранённые изменения" : " · сохранена"}</p>
    </header>
    <form className="flex flex-col gap-5" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <label className="flex flex-col gap-2"><span>Название мира</span><input className={inputClass} maxLength={128} required value={fields.title} onChange={e => update("title", e.target.value)} /></label>
      {groups.map(([name,label,hint]) => <label key={name} className="flex flex-col gap-2"><span>{label}</span>
        <textarea aria-label={label} className={inputClass} rows={name === "world" || name === "laws" ? 5 : 3} value={String(fields[name])} onChange={e => update(name, e.target.value)} />
        <span className="text-xs text-muted">{hint}</span></label>)}
      <label className="flex flex-col gap-2"><span>Сложность</span><select className={inputClass} value={fields.difficulty} onChange={e => update("difficulty", e.target.value as StudioFields["difficulty"])}>
        <option value="easy">Лёгкая</option><option value="normal">Обычная</option><option value="hard">Трудная</option><option value="deadly">Смертельная</option></select></label>
      <label className="flex flex-col gap-2"><span>Исключённые темы</span><input className={inputClass} value={fields.excluded_themes.join(", ")} onChange={e => update("excluded_themes", e.target.value.split(",").map(x => x.trim()))} placeholder="Через запятую" /></label>
      <button className="btn btn-primary self-start" disabled={busy || !dirty || !fields.title.trim()} type="submit">{save.isPending ? "Сохранение…" : "Сохранить мир"}</button>
    </form>
    {error && <p role="alert" className="text-bad">{error instanceof ApiError ? error.message : "Не удалось выполнить действие. Повторите попытку."}</p>}
    <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-5" aria-label="Проверка мира">
      <h2 className="font-heading text-xl">Обсуждение с мастером</h2>
      {dirty && <p className="text-sm text-muted">Сохраните изменения перед проверкой и принятием версии.</p>}
      <button className="btn self-start" disabled={busy || dirty} onClick={() => review.mutate("")}>Проверить мир с мастером</button>
      {receipt?.question && <><p>{receipt.question}</p><label className="flex flex-col gap-2"><span>Ответ мастеру</span><textarea className={inputClass} value={answer} onChange={e => setAnswer(e.target.value)} /></label><button className="btn self-start" disabled={busy || dirty || !answer.trim()} onClick={() => review.mutate(answer)}>Ответить мастеру</button></>}
      {receipt?.notes?.map((note,i) => <p key={i} className="text-sm text-ink-2">{note}</p>)}
      {receipt?.status === "ready" && <p>Мастер готов принять эту редакцию.</p>}
      <button className="btn btn-primary self-start" disabled={busy || dirty || receipt?.status !== "ready"} onClick={() => accept.mutate()}>Принять версию</button>
    </section>
    <section className="flex flex-col gap-3" aria-label="Принятые версии"><h2 className="font-heading text-xl">Принятые версии</h2>
      {(project.data?.published ?? []).map(v => <div key={v.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4"><span>Версия {v.version} · редакция {v.source_revision}</span><button className="btn" disabled={busy} onClick={() => launch.mutate(v.id)}>Запустить версию {v.version}</button></div>)}
      {!project.data?.published?.length && <p className="text-sm text-muted">После принятия здесь появится неизменная версия мира.</p>}
    </section>
  </main>;
}
