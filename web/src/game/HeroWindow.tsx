import { useEffect, type ReactNode } from "react";
import { create } from "zustand";
import type { HeroAttack, HeroSheet } from "../lib/types";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { ABILITIES, ABILITY_ABBR, ABILITY_RU, DAMAGE_RU, signed, SKILLS, useExplain } from "./hero";
import { attack } from "./quick";

type Tab = "stats" | "combat" | "gear" | "state" | "persona" | "log";
const TABS: [Tab, string][] = [
  ["stats", "Характеристики"],
  ["combat", "Бой"],
  ["gear", "Снаряжение"],
  ["state", "Состояние"],
  ["persona", "Личность"],
  ["log", "Журнал"],
];

interface WindowState {
  open: boolean;
  tab: Tab;
  show(tab?: Tab): void;
  hide(): void;
  setTab(tab: Tab): void;
}

export const useHeroWindow = create<WindowState>((set) => ({
  open: false,
  tab: "stats",
  show(tab) {
    set((s) => ({ open: true, tab: tab ?? s.tab }));
  },
  hide() {
    set({ open: false });
  },
  setTab(tab) {
    set({ tab });
  },
}));

/** Число с разбором по клику. */
function Num({ stat, children, className = "" }: { stat: string; children: ReactNode; className?: string }) {
  const explain = useExplain((s) => s.open);
  return (
    <button
      className={`rounded tabular-nums underline decoration-dotted underline-offset-4 hover:text-accent ${className}`}
      onClick={(e) => explain(stat, e.currentTarget)}
      title="Почему такое число"
    >
      {children}
    </button>
  );
}

function Stats({ h }: { h: HeroSheet }) {
  const d = h.derived!;
  const skills = new Set(h.sheet.skills ?? []);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {ABILITIES.map((a) => (
          <div key={a} className="card flex flex-col items-center p-2">
            <span className="text-xs text-muted">{ABILITY_ABBR[a]}</span>
            <Num stat={`ability:${a}`} className="text-xl font-semibold">
              {d.abilities[a]}
            </Num>
            <span className="text-xs">{signed(d.mods[a])}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-4">
        <span>
          Бонус мастерства <Num stat="pb">{signed(d.pb)}</Num>
        </span>
        <span>
          Инициатива <Num stat="initiative">{signed(d.mods.dex)}</Num>
        </span>
        <span>
          Пассивная внимательность <Num stat="passive_perception">{10 + d.skills.perception}</Num>
        </span>
        <span>
          Скорость <Num stat="speed">{d.speed ?? 30} фт</Num>
        </span>
      </div>
      <div>
        <h3 className="mb-1 text-sm text-muted">Спасброски</h3>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          {ABILITIES.map((a) => (
            <span key={a} className="flex justify-between">
              {ABILITY_RU[a]} <Num stat={`save:${a}`}>{signed(d.saves[a])}</Num>
            </span>
          ))}
        </div>
      </div>
      <div>
        <h3 className="mb-1 text-sm text-muted">Навыки (● — владение)</h3>
        <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {SKILLS.map(([key, name, a]) => (
            <span key={key} className="flex justify-between">
              <span>
                <span className={skills.has(key) ? "text-accent" : "text-line"}>●</span> {name}{" "}
                <span className="text-xs text-muted">{ABILITY_ABBR[a]}</span>
              </span>
              <Num stat={`skill:${key}`}>{signed(d.skills[key])}</Num>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Combat({ h }: { h: HeroSheet }) {
  const scene = useGame((s) => s.scene);
  const canAct = useGame((s) => s.actions.includes("chat.play"));
  const reason = useGame((s) => s.blocked["chat.play"]);
  const hide = useHeroWindow((s) => s.hide);
  const targets = (scene?.entities ?? []).filter((e) => e.attitude === "hostile" && e.condition !== "мёртв");
  const d = h.derived!;

  function hit(t: { id: string; name: string }, a: HeroAttack) {
    const err = attack(t.id, t.name, a);
    if (err) toast.error(err);
    else hide();
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="flex gap-4">
        <span>
          КД <Num stat="ac">{d.ac}</Num>
        </span>
        <span>
          Хиты <Num stat="hp">{h.resources.hp}</Num>/<Num stat="hp_max">{h.resources.hp_max}</Num>
        </span>
      </p>
      {!canAct && reason && <p className="text-xs text-warn">{reason}</p>}
      <ul className="flex flex-col gap-3">
        {d.attacks.map((a) => (
          <li key={a.key} className="card flex flex-col gap-2 p-3">
            <p className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold">{a.name}</span>
              <span className="text-sm">
                попадание <Num stat={`attack:${a.key}`}>{signed(a.attack_bonus)}</Num> · урон {a.damage}{" "}
                {DAMAGE_RU[a.damage_type] ?? a.damage_type} · {a.kind === "ranged" ? "дальний бой" : "ближний бой"}
              </span>
            </p>
            {canAct && targets.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {targets.map((t) => (
                  <button key={t.id} className="btn px-2 py-1 text-xs" onClick={() => hit(t, a)}>
                    Атаковать: {t.name}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      {canAct && targets.length === 0 && <p className="text-xs text-muted">Рядом нет врагов: атаковать некого.</p>}
    </div>
  );
}

function Gear({ h }: { h: HeroSheet }) {
  if (!h.inventory.length) return <p className="text-muted">Снаряжения нет.</p>;
  return (
    <ul className="flex flex-col gap-1">
      {h.inventory.map((i) => (
        <li key={i.id} className="flex justify-between gap-2 border-b border-line py-1">
          <span>
            {i.name}
            {i.qty > 1 ? ` ×${i.qty}` : ""}
          </span>
          {i.equipped && <span className="text-xs text-accent">надето</span>}
        </li>
      ))}
    </ul>
  );
}

/** Опыт до следующего уровня полоской: сколько набрано от порога текущего уровня. */
function Xp({ h }: { h: HeroSheet }) {
  const p = h.progress;
  if (!p) return null;
  if (p.next_xp == null) return <p className="text-xs text-muted">Опыт {p.xp} · высший уровень</p>;
  const pct = Math.max(0, Math.min(100, ((p.xp - p.level_xp) / (p.next_xp - p.level_xp)) * 100));
  return (
    <div className="mt-1 flex items-center gap-2 text-xs text-muted" title="Опыт делится поровну между героями отряда">
      <div
        className="h-1.5 w-32 overflow-hidden rounded bg-line"
        role="progressbar"
        aria-label="Опыт до следующего уровня"
        aria-valuemin={p.level_xp}
        aria-valuemax={p.next_xp}
        aria-valuenow={p.xp}
      >
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span>
        Опыт {p.xp} / {p.next_xp}
      </span>
    </div>
  );
}

function State({ h }: { h: HeroSheet }) {
  const r = h.resources;
  const [s, f] = r.death_saves ?? [0, 0];
  const effects = h.derived?.effects ?? [];
  return (
    <div className="flex flex-col gap-3">
      <p>
        Хиты <Num stat="hp">{r.hp}</Num> из <Num stat="hp_max">{r.hp_max}</Num>
        {r.temp_hp ? ` · временные ${r.temp_hp}` : ""}
      </p>
      <p>Кости хитов: {r.hit_dice ?? 0} — тратятся на коротком отдыхе.</p>
      <p>
        Спасброски от смерти: успехи {s}/3, провалы {f}/3
      </p>
      <div>
        <h3 className="mb-1 text-sm text-muted">Эффекты</h3>
        {effects.length === 0 ? (
          <p className="text-muted">Ничего не действует.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {effects.map((e) => (
              <li key={e.id}>
                {e.name}
                {e.stacks > 1 ? ` ×${e.stacks}` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Persona({ h }: { h: HeroSheet }) {
  return (
    <div className="flex flex-col gap-3 font-narration">
      {h.public_bio && (
        <section>
          <h3 className="font-ui text-sm text-muted">Что видят все</h3>
          <p>{h.public_bio}</p>
        </section>
      )}
      {h.personality && (
        <section>
          <h3 className="font-ui text-sm text-muted">Характер</h3>
          <p>{h.personality}</p>
        </section>
      )}
      {h.private_backstory && (
        <section>
          <h3 className="font-ui text-sm text-muted">Тайная история (видите только вы и мастер)</h3>
          <p>{h.private_backstory}</p>
        </section>
      )}
      {h.bonds && h.bonds.length > 0 && (
        <section>
          <h3 className="font-ui text-sm text-muted">Связи, известные отряду</h3>
          <ul>
            {h.bonds.map((b) => (
              <li key={b.question}>
                <span className="text-muted">{b.question} </span>
                {b.answer}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Log() {
  const g = useGame();
  const x = g.explained.hp;
  useEffect(() => {
    if (g.sheet && !x) g.socket?.send("stat.explain", { character_id: g.sheet.id, stat: "hp" });
  }, [g.sheet, g.socket, x]);
  if (!x) return <p className="text-muted">Загружаем журнал…</p>;
  if (x.error) return <p className="text-bad">{x.error}</p>;
  return x.history?.length ? (
    <ul className="flex flex-col gap-1">
      {x.history.map((h, i) => (
        <li key={i} className="border-b border-line py-1">
          {h}
        </li>
      ))}
    </ul>
  ) : (
    <p className="text-muted">Пока герой не получал урона и не лечился.</p>
  );
}

/** Окно героя: вкладки листа. Числа кликабельны и открывают разбор; из «Боя» можно атаковать одной кнопкой. */
export default function HeroWindow() {
  const { open, tab, hide, setTab } = useHeroWindow();
  const sheet = useGame((s) => s.sheet);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector('[aria-label="Почему такое число"]') && hide();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, hide]);

  if (!open || !sheet) return null;
  const ready = !!sheet.derived;
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/50 md:items-center" onMouseDown={(e) => e.target === e.currentTarget && hide()}>
      <div role="dialog" aria-label="Лист героя" className="tf-pop flex max-h-[90dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-xl border border-line bg-surface md:rounded-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line p-4">
          <div>
            <h2 className="text-xl font-semibold">{sheet.name}</h2>
            <p className="text-muted">
              {[sheet.origin_name, sheet.class_name, `${sheet.level} уровень`].filter(Boolean).join(" · ")}
            </p>
            <Xp h={sheet} />
            {sheet.lineage && (
              <p className="text-sm" title={sheet.lineage.features.join(", ")}>
                {sheet.lineage.name}
                {sheet.lineage.caste ? `, каста ${sheet.lineage.caste}` : ""}
              </p>
            )}
          </div>
          <button className="text-2xl leading-none text-muted hover:text-ink" onClick={hide} aria-label="Закрыть">
            ×
          </button>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-line px-2" aria-label="Разделы листа">
          {TABS.map(([t, name]) => (
            <button
              key={t}
              className={`shrink-0 border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent text-ink" : "border-transparent text-muted"}`}
              onClick={() => setTab(t)}
            >
              {name}
            </button>
          ))}
        </nav>
        <div className="overflow-y-auto p-4">
          {!ready && tab !== "persona" ? (
            <p className="text-muted">Лист ещё не собран: закончите героя в конструкторе.</p>
          ) : tab === "stats" ? (
            <Stats h={sheet} />
          ) : tab === "combat" ? (
            <Combat h={sheet} />
          ) : tab === "gear" ? (
            <Gear h={sheet} />
          ) : tab === "state" ? (
            <State h={sheet} />
          ) : tab === "persona" ? (
            <Persona h={sheet} />
          ) : (
            <Log />
          )}
        </div>
      </div>
    </div>
  );
}
