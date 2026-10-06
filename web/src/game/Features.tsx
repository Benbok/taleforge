// Вкладка «Умения» листа героя: что даёт каждое умение класса, когда его применять и кто его исполняет.
// Новичок не знает правил, поэтому у каждого умения короткий русский текст и метка: сервер учтёт сам,
// заявите в ходе (кнопка кладёт фразу в поле ввода) или мастер применит по описанию.
import type { ClassFeature, HeroSheet } from "../lib/types";
import { toast } from "../stores/toasts";
import { useDraft } from "./draft";
import { SKILLS } from "./hero";

const MODE: Record<
  ClassFeature["mode"],
  { label: string; hint: string; cls: string }
> = {
  declare: {
    label: "Заявите в ходе",
    hint: "Само не сработает: скажите мастеру, что применяете умение. Кнопка «В ход» впишет фразу в поле ввода.",
    cls: "border-accent text-accent",
  },
  master: {
    label: "Мастер применит по описанию",
    hint: "Мастер знает об умении и учтёт его, когда оно к месту. Можно напомнить ему своими словами.",
    cls: "border-line text-ink",
  },
  auto: {
    label: "Сервер учтёт сам",
    hint: "Уже в числах листа или срабатывает само: ничего делать не нужно.",
    cls: "border-line text-muted",
  },
};

const ORDER: ClassFeature["mode"][] = ["declare", "master", "auto"];
const SKILL_RU = Object.fromEntries(SKILLS.map(([k, name]) => [k, name]));

export default function Features({
  h,
  onDeclare,
}: {
  h: HeroSheet;
  onDeclare: () => void;
}) {
  const rows = h.class_features ?? [];
  if (rows.length === 0)
    return (
      <p className="text-muted">
        У класса героя пока нет умений на этом уровне.
      </p>
    );
  const declare = (f: ClassFeature) => {
    if (f.uses && f.uses.left === 0) {
      toast.error(
        `«${f.name}» потрачено: вернётся после отдыха (${f.uses.per_ru}).`,
      );
      return;
    }
    useDraft.getState().insert(f.say ?? f.name);
    toast.info(
      `Фраза для «${f.name}» в поле ввода: допишите, на кого или как, и отправьте.`,
    );
    onDeclare();
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Метка у умения говорит, что с ним делать: «Заявите в ходе» — скажите
        мастеру, «Мастер применит» — он учтёт сам по ситуации, «Сервер учтёт
        сам» — уже в числах листа.
      </p>
      {ORDER.map((mode) => {
        const list = rows.filter((r) => r.mode === mode);
        if (list.length === 0) return null;
        return (
          <section key={mode} aria-label={MODE[mode].label}>
            <h3 className="mb-2 text-sm text-muted" title={MODE[mode].hint}>
              {MODE[mode].label}
            </h3>
            <ul className="flex flex-col gap-2">
              {list.map((f) => (
                <FeatureCard
                  key={f.key}
                  f={f}
                  h={h}
                  onDeclare={() => declare(f)}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function FeatureCard({
  f,
  h,
  onDeclare,
}: {
  f: ClassFeature;
  h: HeroSheet;
  onDeclare: () => void;
}) {
  const m = MODE[f.mode];
  const detail = f.skills?.length
    ? f.skills.map((s) => SKILL_RU[s] ?? s).join(", ")
    : f.detail;
  const spent = f.uses && f.uses.left === 0;
  const forms = f.key.startsWith("wild_shape") ? h.wild_shape_forms : undefined;
  return (
    <li
      className={`rounded-lg border border-line p-3 ${spent ? "opacity-60" : ""}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold">
          {f.name}
          {detail ? (
            <span className="font-normal text-muted"> · {detail}</span>
          ) : null}
        </p>
        <span
          className={`rounded-full border px-2 py-0.5 text-xs ${m.cls}`}
          title={m.hint}
        >
          {m.label}
        </span>
      </div>
      {f.text_ru && <p className="mt-1 text-sm">{f.text_ru}</p>}
      {f.how && (
        <p className="mt-1 text-sm text-muted">Как применить: {f.how}</p>
      )}
      {forms && forms.length > 0 && (
        <p className="mt-1 text-sm text-muted">
          Формы: {forms.map((x) => x.name).join(", ")}
        </p>
      )}
      {(f.uses || f.mode === "declare") && (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {f.uses && (
            <span className="text-sm tabular-nums">
              Осталось {f.uses.left} из {f.uses.max}
              {f.uses.unit !== "раз" ? ` ${f.uses.unit}` : ""}
              <span className="text-xs text-muted">
                {" "}
                · вернётся: {f.uses.per_ru}
              </span>
            </span>
          )}
          {f.mode === "declare" && (
            <button
              className="rounded border border-accent px-3 py-1 text-sm text-accent hover:bg-accent hover:text-surface"
              onClick={onDeclare}
              title={`Впишет в поле ввода: «${f.say ?? f.name}»`}
            >
              В ход
            </button>
          )}
        </div>
      )}
    </li>
  );
}
