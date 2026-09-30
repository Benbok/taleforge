import { useEffect, useMemo, useState } from "react";
import ActionButton from "../components/ActionButton";
import SpellDetails from "../builder/SpellDetails";
import { ChoiceCard } from "../builder/ChoiceDetails";
import { api } from "../lib/api";
import { byLevel, LEVEL_RU, spellMeta, type SpellCard, type Spellbook as Book } from "../lib/spells";
import type { HeroSheet } from "../lib/types";
import { useGame } from "../stores/game";
import { toast } from "../stores/toasts";
import { ABILITY_RU, signed } from "./hero";
import { cast } from "./quick";

interface Target {
  id: string;
  name: string;
}

/** Книга заклинаний в игре: числа, ячейки, концентрация и сотворение — в бою и вне боя. */
export default function Spellbook({ h, onCast }: { h: HeroSheet; onCast: () => void }) {
  const b = h.spellbook;
  const [open, setOpen] = useState<string | null>(null);
  const [manage, setManage] = useState(false);
  if (!b) return <p className="text-muted">Класс героя не творит заклинаний.</p>;
  const room = b.room.cantrips + b.room.spells + b.room.prepared;
  const canManage = room > 0 || (b.mode !== "known" && b.can_prepare);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <span>
          Характеристика <b>{ABILITY_RU[b.ability] ?? b.ability}</b>
        </span>
        <span>
          Сл спасброска <b className="tabular-nums">{b.save_dc}</b>
        </span>
        <span>
          Атака заклинанием <b className="tabular-nums">{signed(b.attack)}</b>
        </span>
      </div>
      <Slots b={b} />
      {b.concentration && (
        <p className="text-sm">
          <span className="text-accent">◉</span> Концентрация: «{b.concentration.name}». Новое заклинание с концентрацией
          прервёт его, урон требует спасброска Телосложения.
        </p>
      )}
      {b.source && <p className="font-serif text-xs italic text-muted">{b.source}</p>}

      {canManage && !manage && (
        <button className="btn self-start px-3 py-1.5 text-xs" onClick={() => setManage(true)}>
          {room > 0 ? `Выучить и подготовить новое (${room})` : "Сменить подготовленные"}
        </button>
      )}
      {manage && <Manage h={h} b={b} onClose={() => setManage(false)} />}

      {byLevel(b.spells).map(([lvl, list]) => (
        <section key={lvl} className="flex flex-col gap-2">
          <h3 className="text-sm text-muted">
            {LEVEL_RU(lvl)}
            {lvl > 0 && <SlotDots b={b} level={lvl} />}
          </h3>
          <ul className="flex flex-col gap-2">
            {list.map((s) => (
              <SpellRow
                key={s.id}
                s={s}
                b={b}
                open={open === s.id}
                toggle={() => setOpen(open === s.id ? null : s.id)}
                onCast={onCast}
              />
            ))}
          </ul>
        </section>
      ))}
      {b.spells.length === 0 && <p className="text-muted">Заклинаний пока нет: выберите их кнопкой выше.</p>}
    </div>
  );
}

function Slots({ b }: { b: Book }) {
  const rows = b.slots.map((n, i) => ({ level: i + 1, n, left: b.slots_left[String(i + 1)] ?? 0 })).filter((x) => x.n);
  if (!rows.length && !b.pact_slots) return <p className="text-xs text-muted">Ячеек пока нет: только заговоры.</p>;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Ячейки заклинаний">
      {rows.map((r) => (
        <span key={r.level} title={`Осталось ${r.left} из ${r.n}. Возвращаются после продолжительного отдыха.`}>
          {r.level}-й круг <Dots n={r.n} left={r.left} />
        </span>
      ))}
      {b.pact_slots > 0 && (
        <span title="Ячейки договора возвращаются после короткого отдыха.">
          Договор ({b.pact_level}-й круг) <Dots n={b.pact_slots} left={b.pact_left} />
        </span>
      )}
    </div>
  );
}

function SlotDots({ b, level }: { b: Book; level: number }) {
  const n = b.slots[level - 1] ?? 0;
  if (!n) return null;
  return (
    <span className="ml-2">
      <Dots n={n} left={b.slots_left[String(level)] ?? 0} />
    </span>
  );
}

function Dots({ n, left }: { n: number; left: number }) {
  return (
    <span className="tracking-widest text-accent" aria-label={`осталось ${left} из ${n}`}>
      {"●".repeat(left)}
      <span className="text-line">{"●".repeat(Math.max(0, n - left))}</span>
    </span>
  );
}

/** Ячейки, которыми можно сотворить заклинание этого круга: [круг, подпись]. */
function slotOptions(b: Book, level: number): [number, string][] {
  const out: [number, string][] = [];
  if (b.pact_slots && b.pact_left > 0 && level <= b.pact_level) out.push([b.pact_level, `договор, ${b.pact_level}-й круг`]);
  for (const [k, v] of Object.entries(b.slots_left)) {
    const lvl = Number(k);
    if (lvl >= level && v > 0 && !out.some(([x]) => x === lvl)) out.push([lvl, `${lvl}-й круг (осталось ${v})`]);
  }
  return out.sort((a, b2) => a[0] - b2[0]);
}

function SpellRow({
  s,
  b,
  open,
  toggle,
  onCast,
}: {
  s: SpellCard;
  b: Book;
  open: boolean;
  toggle: () => void;
  onCast: () => void;
}) {
  const scene = useGame((st) => st.scene);
  const heroes = useGame((st) => st.heroes);
  const canAct = useGame((st) => st.actions.includes("chat.play"));
  const blocked = useGame((st) => st.blocked["chat.play"]);
  const combat = scene?.mode === "combat";
  const slots = s.level > 0 ? slotOptions(b, s.level) : [];
  const [slot, setSlot] = useState<number | null>(null);
  const [ritual, setRitual] = useState(false);
  const [target, setTarget] = useState<string>("");

  const targets: Target[] = useMemo(() => {
    const foes = (scene?.entities ?? [])
      .filter((e) => e.kind === "creature" && e.condition !== "мёртв")
      .map((e) => ({ id: e.id, name: e.name, hostile: e.attitude === "hostile" }));
    const allies = Object.values(heroes)
      .filter((x) => !x.dead)
      .map((x) => ({ id: x.id, name: x.id === (useGame.getState().sheet?.id ?? "") ? `${x.name} (вы)` : x.name }));
    if (s.targets === "enemy" || s.targets === "area")
      return [...foes.filter((f) => f.hostile), ...foes.filter((f) => !f.hostile)];
    if (s.targets === "ally") return allies;
    if (s.targets === "any") return [...allies, ...foes];
    return [];
  }, [scene, heroes, s.targets]);

  useEffect(() => {
    if (slot == null && slots.length) setSlot(slots[0][0]);
  }, [slot, slots]);

  const canRitual = s.ritual && !!b.ritual && !combat;
  const usable = s.prepared !== false || (canRitual && b.ritual === "book");

  function go() {
    if (!canAct) return toast.error(blocked ?? "Сейчас действовать нельзя.");
    if (!usable) return toast.error(`«${s.name}» не подготовлено: подготовленные меняют после продолжительного отдыха.`);
    if (combat && !s.combat)
      return toast.error(`«${s.name}» творится ${s.casting_time}: в бою не успеть. Можно после боя.`);
    const asRitual = ritual && canRitual;
    if (s.level > 0 && !asRitual && !slots.length)
      return toast.error(
        `Ячейки ${s.level}-го круга и выше потрачены: они вернутся после ${b.pact_slots ? "отдыха" : "продолжительного отдыха"}.`,
      );
    if (s.targets === "enemy" && !target) return toast.error("Выберите цель заклинания.");
    const t = targets.find((x) => x.id === target) ?? null;
    const lvl = s.level > 0 && !asRitual ? (slot ?? slots[0]?.[0] ?? s.level) : null;
    const err = cast(s.id, s.name, t, lvl && lvl > s.level ? lvl : null, asRitual);
    if (err) return toast.error(err);
    toast.ok(`«${s.name}»: заявлено мастеру`);
    onCast();
  }

  return (
    <li className="card flex flex-col gap-2 p-3">
      <button className="flex flex-wrap items-baseline justify-between gap-2 text-left" onClick={toggle} aria-expanded={open}>
        <span className="font-semibold">
          {s.name}
          {s.prepared === false && <span className="ml-2 text-xs font-normal text-muted">не подготовлено</span>}
        </span>
        <span className="text-xs text-muted">{spellMeta(s)}</span>
      </button>
      {s.flavor && <p className="font-serif italic text-xs text-accent/90 line-clamp-2 leading-relaxed -mt-1">{s.flavor}</p>}
      {open && <SpellDetails s={s} />}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {targets.length > 0 && (
          <select
            className="field py-1 text-xs"
            aria-label="Цель"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">{s.targets === "enemy" ? "— цель —" : s.targets === "area" ? "— куда направить —" : "— на себя —"}</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        )}
        {slots.length > 1 && !ritual && (
          <select
            className="field py-1 text-xs"
            aria-label="Ячейка"
            value={slot ?? ""}
            onChange={(e) => setSlot(Number(e.target.value))}
          >
            {slots.map(([lvl, label]) => (
              <option key={lvl} value={lvl}>
                {label}
              </option>
            ))}
          </select>
        )}
        {canRitual && (
          <label className="flex items-center gap-1" title="Без ячейки, на 10 минут дольше">
            <input type="checkbox" checked={ritual} onChange={(e) => setRitual(e.target.checked)} /> ритуалом
          </label>
        )}
        <button className="btn btn-primary px-3 py-1 text-xs" onClick={go}>
          Сотворить
        </button>
      </div>
    </li>
  );
}

/** Выучить открывшееся с уровнем и сменить подготовленные: выученное не забывается. */
function Manage({ h, b, onClose }: { h: HeroSheet; b: Book; onClose: () => void }) {
  const campaignId = useGame((s) => s.snapshot?.campaign.id);
  const setSheet = useGame((s) => s.setSheet);
  const [list, setList] = useState<SpellCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sheet = h.sheet as Record<string, unknown>;
  const base = {
    cantrips: (sheet.cantrips as string[]) ?? [],
    spells: (sheet.spells as string[]) ?? [],
    prepared: (sheet.prepared as string[]) ?? [],
  };
  const [pick, setPick] = useState(base);

  useEffect(() => {
    api<{ spells: SpellCard[] }>(`/api/campaigns/${campaignId}/characters/${h.id}/spells/options`).then(
      (r) => setList(r.spells),
      (e: Error) => setError(e.message),
    );
  }, [campaignId, h.id]);

  if (error) return <p className="text-bad text-sm">Не удалось загрузить список: {error}</p>;
  if (!list) return <p className="text-muted text-sm">Загружаем заклинания класса…</p>;

  const max = {
    cantrips: base.cantrips.length + b.room.cantrips,
    spells: base.spells.length + b.room.spells,
    prepared: b.prepared ?? 0,
  };
  const leveled = list.filter((s) => s.level > 0);
  const groups: { key: keyof typeof base; title: string; items: SpellCard[]; show: boolean }[] = [
    { key: "cantrips", title: "Заговоры", items: list.filter((s) => s.level === 0), show: b.room.cantrips > 0 },
    {
      key: "spells",
      title: b.mode === "spellbook" ? "Книга заклинаний" : "Известные заклинания",
      items: leveled,
      show: b.mode !== "prepared" && b.room.spells > 0,
    },
    {
      key: "prepared",
      title: "Подготовленные на день",
      items: b.mode === "spellbook" ? leveled.filter((s) => pick.spells.includes(s.id)) : leveled,
      show: b.mode !== "known",
    },
  ];

  function flip(key: keyof typeof base, id: string, title: string) {
    const cur = pick[key];
    if (cur.includes(id)) {
      if (key !== "prepared" && base[key].includes(id)) return toast.info("Выученное не забывается: убрать можно только новое.");
      if (key === "prepared" && !b.can_prepare && base.prepared.includes(id))
        return toast.info("Подготовленные меняют после продолжительного отдыха; сейчас можно только добавить.");
      setPick({ ...pick, [key]: cur.filter((x) => x !== id) });
      return;
    }
    if (cur.length >= max[key]) return toast.info(`${title}: уже ${max[key]} из ${max[key]}. Уберите одно, чтобы взять другое.`);
    setPick({ ...pick, [key]: [...cur, id] });
  }

  async function save() {
    const view = await api<HeroSheet>(`/api/campaigns/${campaignId}/characters/${h.id}/spells`, {
      method: "PUT",
      body: pick,
    });
    setSheet({ ...h, ...view });
    onClose();
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-accent/50 bg-raised/40 p-3">
      {groups
        .filter((g) => g.show)
        .map((g) => (
          <fieldset key={g.key} className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-semibold text-accent">
              {g.title}: {pick[g.key].length} из {max[g.key]}
            </legend>
            {g.items.length === 0 ? (
              <p className="text-xs text-muted">Сначала запишите заклинания в книгу.</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {g.items.map((s) => {
                  const on = pick[g.key].includes(s.id);
                  return (
                    <ChoiceCard
                      key={s.id}
                      name={s.name}
                      role="checkbox"
                      selected={on}
                      onPick={() => flip(g.key, s.id, g.title)}
                      details={<SpellDetails s={s} />}
                      className={`flex w-full flex-col rounded-md border px-3 py-2 pr-11 text-left ${
                        on ? "border-accent bg-accent/10" : "border-line hover:border-accent/60"
                      }`}
                    >
                      <span className={`text-sm font-semibold ${on ? "text-accent" : ""}`}>
                        {on ? "✓ " : ""}
                        {s.name}
                      </span>
                      {s.flavor && (
                        <span className="font-serif italic text-xs text-accent/90 line-clamp-2 leading-relaxed">
                          {s.flavor}
                        </span>
                      )}
                      <span className="text-[11px] text-muted">{spellMeta(s)}</span>
                    </ChoiceCard>
                  );
                })}
              </div>
            )}
          </fieldset>
        ))}
      <div className="flex gap-2">
        <ActionButton primary run={save} done="Книга заклинаний обновлена" className="px-3 py-1.5 text-xs">
          Сохранить
        </ActionButton>
        <button className="btn px-3 py-1.5 text-xs" onClick={onClose}>
          Отмена
        </button>
      </div>
    </div>
  );
}
