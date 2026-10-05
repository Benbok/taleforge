import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import ActionButton from "../components/ActionButton";
import { api, getToken } from "../lib/api";
import { toast } from "../stores/toasts";
import CustomSelect from "../components/CustomSelect";

export interface TrackCard {
  id: string;
  file: string;
  layer: string;
  title: string;
  hint?: string;
  moods?: string[];
  places?: string[];
  gain_db?: number;
  packs?: string[];
  cue?: string | string[] | null;
  off?: boolean;
  url?: string;
  size?: number;
}

interface Library {
  dir: string;
  tracks: TrackCard[];
  unsorted: string[];
  errors: string[];
  layers: string[];
  moods: string[];
  cues: string[];
  packs: { id: string; name: string }[];
}

export const LAYER_LABELS: Record<string, string> = { music: "Музыка", sfx: "Эффекты" };
const LAYER_HINTS: Record<string, string> = {
  music: "фон сцены: звучит, пока не сменится настроение или место",
  sfx: "короткий звук один раз: на событие игры",
};
const MOOD_LABELS: Record<string, string> = {
  calm: "покой",
  warm: "тепло",
  mystery: "тайна",
  wonder: "чудо",
  dread: "тревога",
  horror: "ужас",
  sorrow: "печаль",
  tension: "напряжение",
  chase: "погоня",
  battle: "бой",
  heroic: "героика",
  triumph: "триумф",
};
const CUE_LABELS: Record<string, string> = {
  death: "гибель героя",
  victory: "победа в бою",
  combat: "начало боя",
  secret: "раскрыта тайна",
  levelup: "новый уровень",
  crit: "критический успех",
  fumble: "критический провал",
  kill: "враг повержен",
  spell: "заклинание",
  hazard: "опасность",
  effect: "наложено состояние",
  hit: "попадание",
  rest: "отдых",
};
const SHORT = 10; // секунд: файл короче — скорее эффект, чем музыка

export function cueList(cue: TrackCard["cue"]): string[] {
  return cue ? (Array.isArray(cue) ? cue : [cue]) : [];
}

/** Длина файла в секундах: по ней новый файл сразу получает вид. Не прочиталась — null. */
async function durationOf(path: string): Promise<number | null> {
  try {
    const blob = await (await authed(path)).blob();
    const url = URL.createObjectURL(blob);
    return await new Promise((resolve) => {
      const a = new Audio();
      a.preload = "metadata";
      a.onloadedmetadata = () => {
        URL.revokeObjectURL(url);
        resolve(Number.isFinite(a.duration) ? a.duration : null);
      };
      a.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      a.src = url;
    });
  } catch {
    return null;
  }
}

/** Название из имени файла: «rolling_war_drums.mp3» → «Rolling war drums». */
export function titleOf(file: string): string {
  const t = file.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : file;
}

async function authed(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${getToken() ?? ""}` } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `ошибка сервера (${res.status})`);
  }
  return res;
}

/** id карточки из имени файла: латиница, цифры, _ и -; кириллица отбрасывается, тогда «track». Занятый id — с номером. */
export function suggestId(file: string, taken: string[]): string {
  const base =
    file
      .replace(/\.[^.]+$/, "")
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 48) || "track";
  let id = base;
  for (let n = 2; taken.includes(id); n++) id = `${base}_${n}`;
  return id;
}

/** Прослушивание в админке: файл запрашивается с токеном, играет один. */
function Listen({ path }: { path: string }) {
  const ref = useRef<HTMLAudioElement | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => ref.current?.pause(), []);

  async function toggle() {
    if (state === "playing") {
      ref.current?.pause();
      return;
    }
    setError(null);
    try {
      if (!ref.current) {
        setState("loading");
        const blob = await (await authed(path)).blob();
        const a = new Audio(URL.createObjectURL(blob));
        a.onplay = () => setState("playing");
        a.onpause = () => setState("idle");
        a.onended = () => setState("idle");
        ref.current = a;
      }
      await ref.current.play();
    } catch (e) {
      setState("idle");
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" className="btn px-2 py-0.5 text-xs" onClick={toggle} aria-label="Прослушать">
        {state === "loading" ? "…" : state === "playing" ? "❚❚ Стоп" : "▶ Слушать"}
      </button>
      {error && <span className="text-xs text-bad">Не играет: {error}</span>}
    </span>
  );
}

function Chips({
  all,
  labels,
  value,
  onChange,
}: {
  all: string[];
  labels: Record<string, string>;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {all.map((m) => {
        const on = value.includes(m);
        return (
          <button
            key={m}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== m) : [...value, m])}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? "border-accent bg-accent/15 text-accent" : "border-line text-muted"}`}
          >
            {labels[m] ?? m}
          </button>
        );
      })}
    </div>
  );
}

/** Карточка трека: музыка или эффект, настроения или события, миры. Сохраняется в tracks.yaml. */
function CardForm({
  lib,
  initial,
  isNew,
  onDone,
}: {
  lib: Library;
  initial: TrackCard;
  isNew: boolean;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [c, setC] = useState<TrackCard>(initial);
  const [places, setPlaces] = useState((initial.places ?? []).join(", "));
  const set = (patch: Partial<TrackCard>) => setC((x) => ({ ...x, ...patch }));
  const music = c.layer === "music";

  async function save() {
    if (!c.title.trim()) throw new Error("впишите название: его видят игроки");
    if (music && !(c.moods ?? []).length) throw new Error("отметьте хотя бы одно настроение: по нему движок выбирает музыку");
    const body: TrackCard = {
      ...c,
      moods: music ? c.moods : [],
      places: music
        ? places
            .split(",")
            .map((p) => p.trim())
            .filter(Boolean)
        : [],
      cue: music ? null : cueList(c.cue),
    };
    await api(`/api/admin/audio/tracks/${encodeURIComponent(c.id)}`, { method: "PUT", body });
    await qc.invalidateQueries({ queryKey: ["admin-audio"] });
    toast.ok(isNew ? `Трек ${c.title} добавлен в библиотеку` : `Карточка ${c.title} сохранена`);
    onDone();
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-raised/40 p-4">
      <div className="flex flex-wrap gap-2">
        {lib.layers.map((l) => (
          <button
            key={l}
            type="button"
            aria-pressed={c.layer === l}
            onClick={() => set({ layer: l })}
            className={`rounded-lg border px-3 py-1.5 text-left text-xs ${c.layer === l ? "border-accent bg-accent/10 text-ink" : "border-line text-muted"}`}
          >
            <span className="block font-semibold">{LAYER_LABELS[l] ?? l}</span>
            <span className="block text-[11px]">{LAYER_HINTS[l]}</span>
          </button>
        ))}
      </div>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Название для игроков
        <input className="field" value={c.title} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      </label>
      {music ? (
        <>
          <div className="flex flex-col gap-1 text-xs text-muted">
            Настроение: под какие сцены подходит
            <Chips all={lib.moods} labels={MOOD_LABELS} value={c.moods ?? []} onChange={(moods) => set({ moods })} />
          </div>
          <label className="flex flex-col gap-1 text-xs text-muted">
            Места, через запятую (необязательно: такой трек движок предпочтёт там)
            <input className="field" value={places} placeholder="tavern, carcass, mine" onChange={(e) => setPlaces(e.target.value)} />
          </label>
        </>
      ) : (
        <div className="flex flex-col gap-1 text-xs text-muted">
          Когда звучит (ничего не отмечено — включает мастер по сюжету)
          <Chips all={lib.cues} labels={CUE_LABELS} value={cueList(c.cue)} onChange={(cue) => set({ cue })} />
        </div>
      )}
      <div className="flex flex-col gap-1 text-xs text-muted">
        Миры (пусто — общий трек для всех миров)
        <Chips
          all={lib.packs.map((p) => p.id)}
          labels={Object.fromEntries(lib.packs.map((p) => [p.id, p.name]))}
          value={c.packs ?? []}
          onChange={(packs) => set({ packs })}
        />
      </div>
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={!!c.off} onChange={(e) => set({ off: e.target.checked })} />
        Выключен: в игре не звучит
      </label>
      <div className="flex flex-wrap gap-2">
        <ActionButton primary run={save}>
          {isNew ? "Добавить в библиотеку" : "Сохранить"}
        </ActionButton>
        <button type="button" className="btn" onClick={onDone}>
          Отмена
        </button>
      </div>
    </div>
  );
}

/** Новый файл: вид угадывается по длине (короткий — эффект), название — из имени файла. */
function NewCard({ lib, name, taken, world, onDone }: { lib: Library; name: string; taken: string[]; world: string; onDone: () => void }) {
  const [layer, setLayer] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void durationOf(`/api/admin/audio/files/${encodeURIComponent(name)}`).then((d) => {
      if (live) setLayer(d !== null && d < SHORT ? "sfx" : "music");
    });
    return () => {
      live = false;
    };
  }, [name]);
  if (!layer) return <p className="text-xs text-muted">Слушаю файл, чтобы понять, музыка это или эффект…</p>;
  return (
    <CardForm
      lib={lib}
      isNew
      initial={{ id: suggestId(name, taken), file: name, layer, title: titleOf(name), packs: world ? [world] : [] }}
      onDone={onDone}
    />
  );
}

/** Библиотека звука: треки по слоям, загрузка в папку проекта, привязка к мирам. */
export default function AudioSection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-audio"], queryFn: () => api<Library>("/api/admin/audio") });
  const [editing, setEditing] = useState<string | null>(null);
  const [world, setWorld] = useState<string>("");
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const lib = q.data;

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setUploadError(null);
    let n = 0;
    try {
      for (const f of Array.from(files)) {
        setUploading(`Загружаю ${f.name}…`);
        await authed(`/api/admin/audio/files?name=${encodeURIComponent(f.name)}`, {
          method: "POST",
          headers: { "Content-Type": f.type || "application/octet-stream" },
          body: f,
        });
        n++;
      }
      toast.ok(n === 1 ? "Файл загружен: разберите его ниже" : `Загружено файлов: ${n}. Разберите их ниже`);
    } catch (e) {
      setUploadError(`Загружено ${n} из ${files.length}. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(null);
      await qc.invalidateQueries({ queryKey: ["admin-audio"] });
    }
  }

  async function toggleWorld(t: TrackCard, on: boolean) {
    const packs = on ? [...(t.packs ?? []), world] : (t.packs ?? []).filter((p) => p !== world);
    await api(`/api/admin/audio/tracks/${encodeURIComponent(t.id)}`, { method: "PUT", body: { ...t, packs } });
    await qc.invalidateQueries({ queryKey: ["admin-audio"] });
    const name = lib?.packs.find((p) => p.id === world)?.name ?? world;
    toast.ok(on ? `${t.title}: теперь звучит в мире ${name}` : `${t.title}: больше не привязан к миру ${name}`);
  }

  const taken = lib?.tracks.map((t) => t.id) ?? [];

  return (
    <section className="card flex flex-col gap-5 border border-line bg-surface p-5 sm:p-6" aria-label="Звук">
      <div>
        <h2 className="font-heading text-xl font-bold tracking-wide text-ink sm:text-2xl">Звук</h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
          Музыка и эффекты игры. Музыку движок выбирает сам по настроению сцены и месту, эффекты играет на события из
          карточки: начало боя, крит, заклинание, победа. Треки без привязки к миру — общие; сначала берутся треки мира
          кампании. Звук включает владелец кампании в её настройках.
        </p>
        {lib && <p className="mt-1 font-mono text-xs text-muted">Папка: {lib.dir}</p>}
      </div>
      {q.isError && <p className="text-sm text-bad">{String(q.error.message)}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <label className="btn btn-outline-copper cursor-pointer">
          Загрузить файлы
          <input
            type="file"
            accept=".ogg,.opus,.mp3,.wav,.m4a,audio/*"
            multiple
            className="sr-only"
            onChange={(e) => {
              void upload(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
        {uploading && <span className="text-xs text-muted">{uploading}</span>}
        {uploadError && <span className="text-xs text-bad">{uploadError}</span>}
        <span className="text-xs text-muted">OGG, MP3, WAV или M4A, до 20 МБ.</span>
      </div>

      {lib && lib.errors.length > 0 && (
        <div className="rounded-lg border border-warn/40 bg-warn/5 p-4 text-sm">
          <p className="font-semibold text-warn">В tracks.yaml есть ошибки — эти треки мастер не видит:</p>
          <ul className="mt-1 list-disc pl-5 text-muted">
            {lib.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {lib && lib.unsorted.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="font-heading text-lg text-ink">Неразобранные ({lib.unsorted.length})</h3>
          <p className="text-xs text-muted">Файлы без карточки в игре не звучат: отметьте настроение музыки или события эффекта.</p>
          {lib.unsorted.map((name) => (
            <div key={name} className="flex flex-col gap-2 rounded-lg border border-line p-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-sm">{name}</span>
                <Listen path={`/api/admin/audio/files/${encodeURIComponent(name)}`} />
                <button type="button" className="btn btn-outline-copper px-2 py-0.5 text-xs" onClick={() => setEditing(`new:${name}`)}>
                  Разобрать
                </button>
                <ActionButton
                  danger
                  className="px-2 py-0.5 text-xs"
                  confirm={`Удалить файл ${name} из папки?`}
                  done={`Файл ${name} удалён`}
                  run={async () => {
                    await api(`/api/admin/audio/files/${encodeURIComponent(name)}`, { method: "DELETE" });
                    await qc.invalidateQueries({ queryKey: ["admin-audio"] });
                  }}
                >
                  Удалить
                </ActionButton>
              </div>
              {editing === `new:${name}` && <NewCard lib={lib} name={name} taken={taken} world={world} onDone={() => setEditing(null)} />}
            </div>
          ))}
        </div>
      )}

      {lib && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Мир:</span>
          <CustomSelect
            value={world}
            options={[
              { value: "", label: "все треки" },
              ...lib.packs.map((p) => ({ value: p.id, label: p.name })),
            ]}
            onChange={setWorld}
          />
          {world && <span className="text-xs text-muted">Отметьте треки, которые подходят этому миру.</span>}
        </div>
      )}

      {lib &&
        lib.layers.map((layer) => {
          const items = lib.tracks.filter((t) => t.layer === layer);
          return (
            <div key={layer} className="flex flex-col gap-2">
              <h3 className="font-heading text-lg text-ink">
                {LAYER_LABELS[layer]} <span className="text-sm text-muted">· {LAYER_HINTS[layer]} · {items.length}</span>
              </h3>
              {items.length === 0 && <p className="text-xs text-muted">Пока пусто.</p>}
              {items.map((t) => {
                const bound = !!world && (t.packs ?? []).includes(world);
                return (
                  <div key={t.id} className={`flex flex-col gap-2 rounded-lg border border-line p-3 ${t.off ? "opacity-60" : ""}`}>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      {world && (
                        <input
                          type="checkbox"
                          checked={bound}
                          aria-label={`Привязать ${t.title} к миру`}
                          onChange={(e) =>
                            void toggleWorld(t, e.target.checked).catch((err) =>
                              toast.error(`Привязка не сохранилась: ${err instanceof Error ? err.message : String(err)}`),
                            )
                          }
                        />
                      )}
                      <span className="font-semibold text-ink">{t.title}</span>
                      {(t.moods ?? []).length > 0 && (
                        <span className="text-xs text-muted">{(t.moods ?? []).map((m) => MOOD_LABELS[m] ?? m).join(", ")}</span>
                      )}
                      {cueList(t.cue).map((x) => (
                        <span key={x} className="rounded bg-accent/15 px-1.5 text-[11px] text-accent">
                          {CUE_LABELS[x] ?? x}
                        </span>
                      ))}
                      <span className="text-xs text-muted">
                        {(t.packs ?? []).length
                          ? (t.packs ?? []).map((p) => lib.packs.find((x) => x.id === p)?.name ?? p).join(", ")
                          : "общий"}
                      </span>
                      {t.off && <span className="text-xs text-warn">выключен</span>}
                      <span className="ml-auto flex items-center gap-2">
                        {t.url && <Listen path={t.url} />}
                        <button type="button" className="btn px-2 py-0.5 text-xs" onClick={() => setEditing(editing === t.id ? null : t.id)}>
                          Карточка
                        </button>
                      </span>
                    </div>
                    {t.hint && <p className="text-xs text-muted">{t.hint}</p>}
                    {editing === t.id && (
                      <>
                        <CardForm lib={lib} initial={t} isNew={false} onDone={() => setEditing(null)} />
                        <div className="flex gap-2">
                          <ActionButton
                            danger
                            className="px-2 py-0.5 text-xs"
                            confirm={`Убрать ${t.title} из библиотеки и удалить файл?`}
                            done={`${t.title} удалён`}
                            run={async () => {
                              await api(`/api/admin/audio/tracks/${encodeURIComponent(t.id)}?delete_file=true`, { method: "DELETE" });
                              setEditing(null);
                              await qc.invalidateQueries({ queryKey: ["admin-audio"] });
                            }}
                          >
                            Удалить трек и файл
                          </ActionButton>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
    </section>
  );
}
