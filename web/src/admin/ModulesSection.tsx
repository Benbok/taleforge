import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import ActionButton from "../components/ActionButton";
import { api, getToken } from "../lib/api";
import {
  STATUS_LABEL,
  anyBusy,
  addRect,
  cellAt,
  inRoom,
  isBusy,
  placeMark,
  toggleBlocked,
  unplaced,
  uploadRaw,
  type MapGrid,
  type MapMark,
  type ModuleFull,
  type ModuleMap,
  type ModuleShort,
} from "../lib/modules";
import { toast } from "../stores/toasts";

const COUNT_LABELS: Record<string, string> = {
  locations: "Места",
  rooms: "Комнаты",
  creatures: "Свои существа",
  items: "Свои предметы",
  hooks: "Зацепки",
  acts: "Акты",
};

function StatusBadge({ status }: { status: ModuleShort["status"] }) {
  const tone =
    status === "published"
      ? "border-patina/50 bg-patina/10 text-patina"
      : status === "failed"
        ? "border-bad/50 bg-bad/10 text-bad"
        : status === "review"
          ? "border-accent/50 bg-accent/10 text-accent"
          : "border-line bg-raised text-muted";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-xs ${tone}`}
    >
      {isBusy(status) && (
        <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
      )}
      {STATUS_LABEL[status]}
    </span>
  );
}

/** Готовые приключения: книга PDF и карты → разбор ИИ → проверка админом → публикация в библиотеку. */
export default function ModulesSection() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["modules"],
    queryFn: () => api<ModuleShort[]>("/api/admin/modules"),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((m) => isBusy(m.status)) ? 3000 : false,
  });
  const [open, setOpen] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");

  return (
    <div className="flex flex-col gap-6" aria-label="Готовые приключения">
      <section className="card p-5 sm:p-6 border border-line bg-surface">
        <h2 className="font-heading text-xl sm:text-2xl font-bold tracking-wide text-ink">
          Готовые приключения
        </h2>
        <p className="mt-1 text-sm text-muted max-w-2xl leading-relaxed">
          Загрузите опубликованное приключение в PDF и его карты. ИИ разберёт
          книгу на места, комнаты, столкновения и сюжет, найдёт номера комнат на
          картах. Проверьте итог и опубликуйте: приключение появится в
          библиотеке, и по нему можно будет начать кампанию на правилах SRD.
        </p>
      </section>

      <section className="card p-5 sm:p-6 border border-line bg-surface flex flex-col gap-4">
        <h3 className="font-heading text-lg font-bold text-ink">
          Загрузить книгу
        </h3>
        <div className="rounded-[12px] border-2 border-dashed border-line bg-raised/30 p-5 transition hover:border-accent/60">
          <label className="flex flex-col sm:flex-row items-center justify-center gap-3 cursor-pointer text-center sm:text-left">
            <span className="btn btn-outline-copper text-xs font-mono tracking-wider">
              ВЫБРАТЬ PDF
            </span>
            <span className="text-xs sm:text-sm text-muted">
              {file ? (
                <span className="font-mono text-ink font-semibold">
                  {file.name} · {Math.ceil(file.size / 1024)} КБ
                </span>
              ) : (
                "Файл не выбран"
              )}
            </span>
            <input
              type="file"
              className="sr-only"
              accept=".pdf,application/pdf"
              aria-label="Книга приключения"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">
            Пожелание к разбору (необязательно)
          </span>
          <input
            className="field"
            value={note}
            maxLength={2000}
            placeholder="Например: карта убежища культа будет позже"
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <div>
          <ActionButton
            primary
            className="text-xs sm:text-sm font-mono tracking-wider"
            run={async () => {
              if (!file) throw new Error("Выберите PDF приключения");
              const q = new URLSearchParams({ name: file.name, note });
              const m = await uploadRaw<ModuleFull>(
                `/api/admin/modules?${q}`,
                file,
              );
              setFile(null);
              setNote("");
              setOpen(m.id);
              await qc.invalidateQueries({ queryKey: ["modules"] });
              toast.ok("Книга загружена: ИИ начал разбор");
            }}
          >
            ЗАГРУЗИТЬ И РАЗОБРАТЬ
          </ActionButton>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="px-1 font-heading text-lg font-semibold tracking-wide text-ink">
          Библиотека
        </h3>
        {list.isError && (
          <div className="card border-bad/40 bg-bad/5 p-4 text-sm text-bad">
            Не удалось загрузить список: {(list.error as Error).message}
          </div>
        )}
        {list.isSuccess && list.data.length === 0 && (
          <div className="card p-6 text-center text-sm text-muted">
            Приключений пока нет.
          </div>
        )}
        {(list.data ?? []).map((m) => (
          <div key={m.id} className="card p-5">
            <button
              type="button"
              className="flex w-full flex-wrap items-baseline justify-between gap-2 text-left"
              aria-expanded={open === m.id}
              onClick={() => setOpen(open === m.id ? null : m.id)}
            >
              <span className="font-heading text-lg font-bold text-ink">
                {m.title}
              </span>
              <span className="flex items-center gap-2">
                {m.pack_version && (
                  <span className="font-mono text-xs text-muted">
                    v{m.pack_version}
                  </span>
                )}
                <StatusBadge status={m.status} />
              </span>
            </button>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {m.pages > 0 && <Chip label="Страниц" value={m.pages} />}
              {Object.entries(m.counts).map(([k, n]) => (
                <Chip key={k} label={COUNT_LABELS[k] ?? k} value={n ?? 0} />
              ))}
              <Chip label="Карт" value={m.maps} />
            </div>
            {m.status === "failed" && m.error && (
              <p className="mt-2 text-sm text-bad">Причина: {m.error}</p>
            )}
            {open === m.id && (
              <ModuleDetail id={m.id} onGone={() => setOpen(null)} />
            )}
          </div>
        ))}
      </section>
    </div>
  );
}

function Chip({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-line bg-raised px-2.5 py-1 font-mono text-xs text-ink-2">
      <span className="text-muted">{label}:</span>
      <span className="font-semibold text-accent">{value}</span>
    </span>
  );
}

function ModuleDetail({ id, onGone }: { id: string; onGone: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["module", id],
    queryFn: () => api<ModuleFull>(`/api/admin/modules/${id}`),
    refetchInterval: (s) =>
      s.state.data && anyBusy(s.state.data) ? 3000 : false,
  });
  const [note, setNote] = useState<string | null>(null);
  const m = q.data;

  async function refresh(next?: ModuleFull) {
    if (next) qc.setQueryData(["module", id], next);
    await qc.invalidateQueries({ queryKey: ["modules"] });
    await qc.invalidateQueries({ queryKey: ["module", id] });
  }

  if (q.isError)
    return (
      <p className="mt-3 text-sm text-bad">
        Не удалось открыть: {(q.error as Error).message}
      </p>
    );
  if (!m) return <p className="mt-3 text-sm text-muted">Загрузка…</p>;
  const d = m.draft;
  const busy = isBusy(m.status);

  return (
    <div className="mt-4 flex flex-col gap-4 border-t border-line pt-4 text-sm">
      {busy && (
        <p className="text-muted" role="status">
          {STATUS_LABEL[m.status]}… Страница обновится сама.
        </p>
      )}
      {d && (
        <>
          <p className="text-ink-2">{d.summary}</p>
          <p className="font-mono text-xs text-muted">
            {d.levels ? `Уровни ${d.levels.start}–${d.levels.end}` : ""}
            {d.party_size ? ` · героев: ${d.party_size}` : ""} · опыт по этапам
            книги
          </p>
          {d.hooks.length > 0 && (
            <Block title="Зацепки">
              {d.hooks.map((h) => (
                <li key={h.id}>{h.title}</li>
              ))}
            </Block>
          )}
          <Block title="Места и комнаты">
            {d.locations.map((loc) => (
              <li key={loc.id}>
                <span className="font-semibold text-ink">{loc.name}</span>{" "}
                <span className="font-mono text-xs text-faint">({loc.id})</span>
                :{" "}
                {loc.rooms
                  .map((r) => (r.number ? `${r.number}. ${r.name}` : r.name))
                  .join("; ")}
              </li>
            ))}
          </Block>
          {d.creatures.length > 0 && (
            <Block title="Существа, которых нет в SRD">
              {d.creatures.map((c) => (
                <li key={c.id}>
                  {c.name}{" "}
                  <span className="font-mono text-xs text-faint">
                    на основе {c.base_ref}
                  </span>
                  {c.book_note && (
                    <span className="block text-xs text-warn">
                      Отличие от книги: {c.book_note}
                    </span>
                  )}
                </li>
              ))}
            </Block>
          )}
          {d.items.length > 0 && (
            <Block title="Предметы, которых нет в SRD">
              {d.items.map((i) => (
                <li key={i.id}>
                  {i.name}
                  {i.book_note && (
                    <span className="block text-xs text-warn">
                      Отличие от книги: {i.book_note}
                    </span>
                  )}
                </li>
              ))}
            </Block>
          )}
          {d.notes.length > 0 && (
            <Block title="Что ИИ придумал сам" tone="warn">
              {d.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </Block>
          )}
          {m.warnings.length > 0 && (
            <Block title="Предупреждения проверки" tone="warn">
              {m.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </Block>
          )}
        </>
      )}

      <MapsBlock m={m} onChange={refresh} />

      <div className="flex flex-col gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-muted">Пожелание к новому разбору</span>
          <input
            className="field"
            value={note ?? m.note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-3">
          {(m.status === "review" || m.status === "published") && (
            <ActionButton
              primary
              confirm={
                m.status === "published"
                  ? "Выпустить новую версию приключения?"
                  : undefined
              }
              run={async () =>
                refresh(
                  await api<ModuleFull>(`/api/admin/modules/${id}/publish`, {
                    method: "POST",
                  }),
                )
              }
              done="Приключение опубликовано в библиотеке"
            >
              {m.status === "published"
                ? "ОПУБЛИКОВАТЬ НОВУЮ ВЕРСИЮ"
                : "ОПУБЛИКОВАТЬ"}
            </ActionButton>
          )}
          {!busy && (
            <ActionButton
              confirm="Разобрать книгу заново? Отметки на картах ИИ найдёт заново."
              run={async () =>
                refresh(
                  await api<ModuleFull>(`/api/admin/modules/${id}/import`, {
                    body: { note: note ?? m.note },
                  }),
                )
              }
              done="Разбор начат заново"
            >
              РАЗОБРАТЬ ЗАНОВО
            </ActionButton>
          )}
          {!busy && !m.pack_id && (
            <ActionButton
              danger
              confirm={`Удалить «${m.title}» вместе с книгой и картами?`}
              run={async () => {
                await api(`/api/admin/modules/${id}`, { method: "DELETE" });
                await qc.invalidateQueries({ queryKey: ["modules"] });
                onGone();
              }}
              done="Приключение удалено"
            >
              УДАЛИТЬ
            </ActionButton>
          )}
        </div>
      </div>
    </div>
  );
}

function Block({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "warn";
  children: React.ReactNode;
}) {
  return (
    <div
      className={
        tone === "warn"
          ? "rounded-[8px] border border-warn/30 bg-warn/10 p-3"
          : ""
      }
    >
      <h4
        className={`font-heading text-sm font-bold ${tone === "warn" ? "text-warn" : "text-ink"}`}
      >
        {title}
      </h4>
      <ul className="mt-1 list-disc pl-5 space-y-1 text-ink-2">{children}</ul>
    </div>
  );
}

function MapsBlock({
  m,
  onChange,
}: {
  m: ModuleFull;
  onChange: (next?: ModuleFull) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <div className="flex flex-col gap-3">
      <h4 className="font-heading text-sm font-bold text-ink">Карты</h4>
      {m.map_list.length === 0 && (
        <p className="text-muted">
          Карт нет. Загрузите картинку карты каждого места.
        </p>
      )}
      {m.map_list.map((x) => (
        <MapEditor key={x.id} module={m} map={x} onChange={onChange} />
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <label className="btn btn-outline-copper cursor-pointer text-xs font-mono tracking-wider">
          ВЫБРАТЬ КАРТУ
          <input
            type="file"
            className="sr-only"
            accept="image/png,image/jpeg,image/webp"
            aria-label="Картинка карты"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        {file && (
          <span className="font-mono text-xs text-ink">{file.name}</span>
        )}
        <ActionButton
          run={async () => {
            if (!file) throw new Error("Выберите картинку карты");
            const next = await uploadRaw<ModuleFull>(
              `/api/admin/modules/${m.id}/maps?${new URLSearchParams({ name: file.name })}`,
              file,
            );
            setFile(null);
            await onChange(next);
          }}
          done={
            m.draft
              ? "Карта загружена: ИИ ищет номера комнат"
              : "Карта загружена"
          }
        >
          ДОБАВИТЬ КАРТУ
        </ActionButton>
      </div>
    </div>
  );
}

/** Картинка с сервера по токену: тегу img заголовок авторизации не передать. */
function useAuthedImage(url: string): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (!alive || !b) return;
        made = URL.createObjectURL(b);
        setSrc(made);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  return src;
}

type EditMode = "numbers" | "floor" | "blocked";

const NO_GRID: MapGrid = {
  cols: 20,
  rows: 20,
  left: 0,
  top: 0,
  right: 1,
  bottom: 1,
};

/** Сетка, пол комнат и занятые клетки поверх картинки. viewBox в долях картинки. */
function GridOverlay({
  grid,
  marks,
  room,
  corner,
}: {
  grid: MapGrid;
  marks: MapMark[];
  room: string | null;
  corner: [number, number] | null;
}) {
  const w = (grid.right - grid.left) / grid.cols;
  const h = (grid.bottom - grid.top) / grid.rows;
  const x = (c: number) => grid.left + c * w;
  const y = (r: number) => grid.top + r * h;
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {Array.from({ length: grid.cols + 1 }, (_, i) => (
        <line
          key={`c${i}`}
          x1={x(i)}
          x2={x(i)}
          y1={grid.top}
          y2={grid.bottom}
          stroke="var(--tf-accent)"
          strokeOpacity="0.35"
          strokeWidth="0.0015"
        />
      ))}
      {Array.from({ length: grid.rows + 1 }, (_, i) => (
        <line
          key={`r${i}`}
          y1={y(i)}
          y2={y(i)}
          x1={grid.left}
          x2={grid.right}
          stroke="var(--tf-accent)"
          strokeOpacity="0.35"
          strokeWidth="0.0015"
        />
      ))}
      {marks.map((k) => {
        const mine = k.number === room;
        return (
          <g key={k.number} opacity={mine ? 1 : 0.35}>
            {(k.cells ?? []).map(([c0, r0, c1, r1], i) => (
              <rect
                key={i}
                x={x(c0)}
                y={y(r0)}
                width={(c1 - c0 + 1) * w}
                height={(r1 - r0 + 1) * h}
                fill="var(--tf-accent)"
                fillOpacity="0.18"
              />
            ))}
            {(k.blocked ?? []).map(([c, r]) => (
              <rect
                key={`${c}-${r}`}
                x={x(c)}
                y={y(r)}
                width={w}
                height={h}
                fill="var(--tf-ember)"
                fillOpacity="0.45"
              />
            ))}
          </g>
        );
      })}
      {corner && (
        <rect
          x={x(corner[0])}
          y={y(corner[1])}
          width={w}
          height={h}
          fill="none"
          stroke="var(--tf-accent)"
          strokeWidth="0.004"
        />
      )}
    </svg>
  );
}

function MapEditor({
  module: m,
  map,
  onChange,
}: {
  module: ModuleFull;
  map: ModuleMap;
  onChange: (next?: ModuleFull) => Promise<void>;
}) {
  const src = useAuthedImage(`/api/modules/${m.id}/maps/${map.id}`);
  const [loc, setLoc] = useState<string>(map.location_id ?? "");
  const [marks, setMarks] = useState<MapMark[]>(map.marks ?? []);
  const [grid, setGrid] = useState<MapGrid | null>(map.grid ?? null);
  const [mode, setMode] = useState<EditMode>("numbers");
  const [corner, setCorner] = useState<[number, number] | null>(null);
  const numbers = m.room_numbers[loc] ?? [];
  const [pick, setPick] = useState<string | null>(null);
  const dirty =
    loc !== (map.location_id ?? "") ||
    JSON.stringify(marks) !== JSON.stringify(map.marks ?? []) ||
    JSON.stringify(grid) !== JSON.stringify(map.grid ?? null);

  useEffect(() => {
    setLoc(map.location_id ?? "");
    setMarks(map.marks ?? []);
    setGrid(map.grid ?? null);
  }, [map.location_id, map.marks, map.grid]);

  const todo = unplaced(numbers, marks);
  const current = pick ?? (mode === "numbers" ? todo[0] : numbers[0]) ?? null;
  const room = marks.find((k) => k.number === current) ?? null;

  function click(fx: number, fy: number) {
    if (!loc || !current) {
      toast.info(loc ? "Выберите номер комнаты" : "Выберите место карты");
      return;
    }
    if (mode === "numbers") {
      setMarks(placeMark(marks, current, fx, fy));
      setPick(null);
      return;
    }
    if (!grid) {
      toast.info("Сначала включите сетку");
      return;
    }
    if (!room) {
      toast.info(`Сначала поставьте номер ${current} на карту`);
      return;
    }
    const cell = cellAt(grid, fx, fy);
    if (!cell) {
      toast.info("Щелчок вне сетки");
      return;
    }
    const update = (next: MapMark) =>
      setMarks(marks.map((k) => (k.number === current ? next : k)));
    if (mode === "floor") {
      if (!corner) {
        setCorner(cell);
        toast.info("Теперь щёлкните противоположный угол");
      } else {
        update(addRect(room, corner, cell));
        setCorner(null);
      }
      return;
    }
    if (!inRoom(room, cell)) {
      toast.info("Клетка вне пола комнаты: сначала отметьте пол");
      return;
    }
    update(toggleBlocked(room, cell));
  }

  const modeBtn = (id: EditMode, label: string) => (
    <button
      type="button"
      aria-pressed={mode === id}
      className={`rounded border px-2 py-0.5 ${mode === id ? "border-accent bg-accent/20 text-accent" : "border-line text-ink-2"}`}
      onClick={() => {
        setMode(id);
        setCorner(null);
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="rounded-[10px] border border-line p-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-ink">{map.name || map.id}</span>
        {map.status === "reading" && (
          <span className="font-mono text-xs text-muted">
            ИИ ищет номера и клетки…
          </span>
        )}
        {map.status === "pending" && (
          <span className="font-mono text-xs text-muted">
            ждёт разбора книги
          </span>
        )}
        {map.status === "failed" && (
          <span className="text-xs text-bad">Не распознана: {map.error}</span>
        )}
      </div>
      {m.draft && (
        <label className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted">Место на карте:</span>
          <select
            className="field h-8 py-0 text-xs"
            value={loc}
            onChange={(e) => {
              setLoc(e.target.value);
              setMarks([]);
              setPick(null);
            }}
          >
            <option value="">не выбрано</option>
            {m.draft.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {loc && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Щелчок по карте:</span>
          {modeBtn("numbers", "ставит номер")}
          {modeBtn("floor", "отмечает пол комнаты")}
          {modeBtn("blocked", "занята ⇄ свободна")}
          {mode !== "numbers" && room && (room.cells ?? []).length > 0 && (
            <button
              type="button"
              className="text-muted underline hover:text-ink"
              onClick={() =>
                setMarks(
                  marks.map((k) =>
                    k.number === current ? { ...k, cells: [], blocked: [] } : k,
                  ),
                )
              }
            >
              очистить комнату {current}
            </button>
          )}
        </div>
      )}
      {loc && numbers.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Комната:</span>
          {numbers.map((n) => (
            <button
              key={n}
              type="button"
              aria-pressed={current === n}
              className={`rounded border px-2 py-0.5 font-mono ${
                current === n
                  ? "border-accent bg-accent/20 text-accent"
                  : todo.includes(n)
                    ? "border-warn/50 text-warn"
                    : "border-line text-ink-2"
              }`}
              onClick={() => {
                setPick(n);
                setCorner(null);
              }}
            >
              {n}
            </button>
          ))}
        </div>
      )}
      {loc && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!!grid}
              onChange={(e) =>
                setGrid(e.target.checked ? (map.grid ?? NO_GRID) : null)
              }
            />
            <span className="text-muted">Сетка</span>
          </label>
          {grid &&
            (
              [
                ["cols", "столбцов", 1],
                ["rows", "строк", 1],
                ["left", "левый край %", 100],
                ["top", "верх %", 100],
                ["right", "правый край %", 100],
                ["bottom", "низ %", 100],
              ] as const
            ).map(([key, label, scale]) => (
              <label key={key} className="flex items-center gap-1">
                <span className="text-muted">{label}</span>
                <input
                  type="number"
                  className="field h-7 w-16 py-0 text-xs"
                  step={scale === 1 ? 1 : 0.1}
                  value={Math.round(grid[key] * scale * 10) / 10}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (!Number.isFinite(v)) return;
                    setGrid({
                      ...grid,
                      [key]:
                        scale === 1 ? Math.max(1, Math.round(v)) : v / scale,
                    });
                  }}
                />
              </label>
            ))}
        </div>
      )}
      <div
        className="relative w-full max-w-2xl select-none"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          click((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
        }}
      >
        {src ? (
          <img
            src={src}
            alt={`Карта ${map.name}`}
            className="block w-full rounded-[8px]"
            draggable={false}
          />
        ) : (
          <div className="h-40 rounded-[8px] bg-raised" />
        )}
        {grid && (
          <GridOverlay
            grid={grid}
            marks={marks}
            room={mode === "numbers" ? null : current}
            corner={corner}
          />
        )}
        {marks.map((k) => (
          <span
            key={k.number}
            className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-accent bg-bg/80 px-1.5 font-mono text-xs font-bold text-accent"
            style={{ left: `${k.x * 100}%`, top: `${k.y * 100}%` }}
          >
            {k.number}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {dirty && (
          <ActionButton
            primary
            run={async () => {
              if (!loc) throw new Error("Выберите место карты");
              await onChange(
                await api<ModuleFull>(
                  `/api/admin/modules/${m.id}/maps/${map.id}`,
                  {
                    method: "PUT",
                    body: { location_id: loc, grid, marks },
                  },
                ),
              );
            }}
            done="Карта сохранена"
          >
            СОХРАНИТЬ КАРТУ
          </ActionButton>
        )}
        {m.draft && map.status !== "reading" && !isBusy(m.status) && (
          <ActionButton
            confirm={
              dirty
                ? "Несохранённые правки карты пропадут. Искать заново?"
                : undefined
            }
            run={async () =>
              onChange(
                await api<ModuleFull>(
                  `/api/admin/modules/${m.id}/maps/${map.id}/read`,
                  { method: "POST" },
                ),
              )
            }
            done="ИИ ищет номера и клетки на карте"
          >
            РАЗОБРАТЬ КАРТУ ЗАНОВО
          </ActionButton>
        )}
        <ActionButton
          danger
          confirm="Удалить карту?"
          run={async () =>
            onChange(
              await api<ModuleFull>(
                `/api/admin/modules/${m.id}/maps/${map.id}`,
                { method: "DELETE" },
              ),
            )
          }
          done="Карта удалена"
        >
          УДАЛИТЬ КАРТУ
        </ActionButton>
      </div>
    </div>
  );
}
