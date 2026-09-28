import { useEffect, useRef, type ReactNode } from "react";
import { useGame } from "../stores/game";
import { Spinner } from "../components/ActionButton";
import { useDraft } from "./draft";
import { cardActions, TYPE_COLOR, TYPE_ICON, TYPE_NAME } from "./entities";
import { useInspector } from "./inspector";
import { attack } from "./quick";
import { signed } from "./hero";
import { toast } from "../stores/toasts";

const STAT_NAMES: Record<string, string> = { ac: "КБ", hp: "Хиты", hp_max: "из", speed: "Скорость" };

/** Карточка знаний рядом со словом (на телефоне — снизу во всю ширину). Показывает только открытое герою,
 *  закрытые уровни — строкой «ещё можно узнать». Действие подставляет текст в поле ввода, отправляет игрок. */
export default function EntityPopover() {
  const { id, label, anchor, close } = useInspector();
  const card = useGame((s) => (id ? s.cards[id] : undefined));
  const insert = useDraft((s) => s.insert);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [id, close]);

  if (!id) return null;
  const phone = window.innerWidth < 768;
  const style =
    anchor && !phone
      ? {
          left: Math.min(Math.max(8, anchor.left), window.innerWidth - 336),
          top: anchor.bottom + 8 + 320 > window.innerHeight ? Math.max(8, anchor.top - 328) : anchor.bottom + 8,
        }
      : undefined;
  const name = card?.name ?? label;
  const type = card?.type;
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`Карточка: ${name}`}
      className={`tf-pop fixed z-40 max-h-[70dvh] overflow-y-auto border border-line bg-raised p-4 shadow-xl ${
        style ? "w-80 rounded-lg" : "inset-x-0 bottom-0 rounded-t-xl"
      }`}
      style={style}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wide" style={{ color: type ? TYPE_COLOR[type] : undefined }}>
            {type ? `${TYPE_ICON[type]} ${TYPE_NAME[type]}` : "Карточка"}
            {card?.level_name ? ` · ${card.level_name}` : ""}
          </p>
          <h3 className="text-lg font-semibold">{name}</h3>
        </div>
        <button className="text-muted hover:text-ink" onClick={close} aria-label="Закрыть">
          ×
        </button>
      </div>
      {!card && (
        <p className="flex items-center gap-2 text-muted">
          <Spinner /> Вспоминаем, что вы знаете…
        </p>
      )}
      {card?.error && <p className="text-bad">{card.error}</p>}
      {card?.hero && (
        <div className="flex flex-col gap-2">
          <p className="text-muted">
            {[card.hero.origin_name, card.hero.class_name, `${card.hero.level} уровень`].filter(Boolean).join(" · ")}
            {card.hero.dead ? " · погиб" : ""}
          </p>
          {card.hero.public_bio && <p className="font-narration">{card.hero.public_bio}</p>}
          {card.hero.bonds && card.hero.bonds.length > 0 && (
            <Section title="Известно отряду">
              {card.hero.bonds.map((b) => (
                <li key={b.question}>
                  <span className="text-muted">{b.question} </span>
                  {b.answer}
                </li>
              ))}
            </Section>
          )}
          <Learned facts={card.facts} heard={card.heard} />
        </div>
      )}
      {card && !card.error && !card.hero && (
        <div className="flex flex-col gap-2">
          {card.kind_name && card.kind_name !== name && <p className="text-muted">{card.kind_name}</p>}
          {card.description && <p className="font-narration">{card.description}</p>}
          {card.lore && <p className="font-narration text-muted">{card.lore}</p>}
          {card.habits && <p>Повадки: {card.habits}</p>}
          {card.condition && <p>Состояние: {card.condition}</p>}
          {card.attacks && card.attacks.length > 0 && <p>Оружие: {card.attacks.join(", ")}</p>}
          {card.vulnerable && <p>Уязвим: {card.vulnerable.join(", ")}</p>}
          {card.stats && (
            <p className="text-xs">
              {Object.entries(card.stats)
                .filter(([k, v]) => v != null && typeof v !== "object" && STAT_NAMES[k])
                .map(([k, v]) => `${STAT_NAMES[k]} ${v}`)
                .join(" · ")}
            </p>
          )}
          <Learned facts={card.facts} heard={card.heard} />
          {card.locked && card.locked.length > 0 && (
            <p className="text-xs text-muted">Скрыто: ещё можно узнать ({card.locked.join(", ")})</p>
          )}
          {type === "creature" && <QuickAttack id={id} name={name} onDone={close} />}
          <div className="mt-1 flex flex-wrap gap-2">
            {cardActions(type, name).map((a) => (
              <button
                key={a.label}
                className="btn px-2 py-1 text-xs"
                onClick={() => {
                  insert(a.text);
                  close();
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-xs uppercase tracking-wide text-muted">{title}</p>
      <ul className="flex list-none flex-col gap-1 p-0">{children}</ul>
    </div>
  );
}

/** Что именно этот герой узнал в игре: факты от мастера и фразы из рассказа, которые видел этот игрок. */
function Learned({ facts, heard }: { facts?: string[]; heard?: string[] }) {
  return (
    <>
      {facts && facts.length > 0 && (
        <Section title="Вы знаете">
          {facts.map((f) => (
            <li key={f}>• {f}</li>
          ))}
        </Section>
      )}
      {heard && heard.length > 0 && (
        <Section title="Что вы слышали">
          {heard.map((h) => (
            <li key={h} className="border-l-2 border-line pl-2 font-narration text-muted">
              {h}
            </li>
          ))}
        </Section>
      )}
    </>
  );
}

/** Атака одной кнопкой: оружие героя против этого существа. Проверяет сервер, модель намерение не разбирает. */
function QuickAttack({ id, name, onDone }: { id: string; name: string; onDone: () => void }) {
  const sheet = useGame((s) => s.sheet);
  const canAct = useGame((s) => s.actions.includes("chat.play"));
  const attacks = sheet?.derived?.attacks ?? [];
  if (!canAct || !attacks.length) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs uppercase tracking-wide text-muted">Атаковать сразу</p>
      <div className="flex flex-wrap gap-2">
        {attacks.map((a) => (
          <button
            key={a.key}
            className="btn border-creature px-2 py-1 text-xs"
            onClick={() => {
              const err = attack(id, name, a);
              if (err) toast.error(err);
              else onDone();
            }}
          >
            {a.name} {signed(a.attack_bonus)}
          </button>
        ))}
      </div>
    </div>
  );
}
