// Конструктор героя: черновик на клиенте и его проверка. Правила и числа считает сервер (живой лист —
// character-preview), здесь только то, что нужно, чтобы подсказать игроку до запроса.
import type { ClassSpells } from "./spells";
import type { HeroAttack } from "./types";

export interface EquipPart {
  item?: string;
  name?: string;
  qty?: number;
  any?: string;
  other?: string;
}

/** Тексты карточки из пакета мира: строка под именем, метка, коротко и главные особенности. */
export interface CardTexts {
  epithet?: string;
  badge?: string;
  summary?: string;
  highlights?: string[];
}

export interface ClassOption extends CardTexts {
  id: string;
  name: string;
  description: string;
  hit_die: number | null;
  saving_throws: string[];
  proficiencies?: { armor?: string[]; weapons?: string[]; tools?: string[] };
  spellcasting_ability?: string | null;
  subclasses?: { name: string; description: string }[];
  /** Заклинания класса на стартовом уровне; null — класс не колдует. */
  spells?: ClassSpells | null;
  skills_choose: { count?: number; from?: string[] };
  equipment_fixed: { item: string; name?: string; qty?: number }[];
  equipment_choices: EquipPart[][][];
}

export interface AbilityGroup {
  count: number;
  bonus: number;
  from: string[];
  distinct_from_prior: boolean;
}

export interface OriginOption extends CardTexts {
  id: string;
  name: string;
  description: string;
  traits?: { name: string; description: string }[];
  size?: string | null;
  darkvision?: number | null;
  proficiencies?: { skills?: string[]; skills_choose?: { count?: number }; tools?: string[] };
  ability_bonuses: Record<string, number>;
  /** Прибавки на выбор игрока, по порядку; distinct_from_prior — не туда, куда уже выбрано раньше. */
  ability_groups: AbilityGroup[];
  speed: number | null;
  features: string[];
}

export interface BuilderOptions {
  ability_methods: Method[];
  standard_array: number[];
  point_buy: { budget: number; cost: Record<string, number> };
  start_level: number;
  classes: ClassOption[];
  origins: OriginOption[];
  weapons: Record<string, { name: string; group: string | null }>;
}

export type Method = "standard_array" | "point_buy" | "roll";

export interface EquipChoice {
  choice: number;
  option: number;
  items: string[];
}

export interface Draft {
  name: string;
  class_id: string;
  origin_id: string;
  ability_method: Method;
  abilities: Record<string, number | null>;
  /** Выбор прибавок происхождения, по группе на массив. Серверу уходит одним списком по порядку групп. */
  ability_picks: string[][];
  skills: string[];
  equipment_choices: EquipChoice[];
  cantrips: string[];
  spells: string[];
  prepared: string[];
  public_bio: string;
  private_backstory: string;
}

export interface Preview {
  errors: string[];
  derived: {
    abilities: Record<string, number>;
    mods: Record<string, number>;
    ac: number;
    hp_max: number;
    saves: Record<string, number>;
    skills: Record<string, number>;
    pb: number;
    speed: number;
    attacks: HeroAttack[];
    /** Заклинатель: сложность спасброска, бонус атаки и сколько выбрать заклинаний. */
    spellcasting?: {
      ability: string;
      save_dc: number;
      attack: number;
      needs: { cantrips: number; spells: number; prepared: number };
    };
  } | null;
  inventory: { item: string; name: string; qty: number; equipped: boolean }[];
}

/** Сохранённый герой (кампании или профиля), из которого открывается конструктор. */
export interface SavedHero {
  id: string;
  name: string;
  status?: string;
  sheet?: Record<string, unknown> | null;
  public_bio?: string | null;
  private_backstory?: string | null;
  errors?: string[];
}

export const METHOD_RU: Record<Method, string> = {
  standard_array: "Стандартный набор",
  point_buy: "Покупка очков",
  roll: "Броски 4d6",
};

export const METHOD_HINT: Record<Method, string> = {
  standard_array: "Разложите 15, 14, 13, 12, 10 и 8, каждое по разу.",
  point_buy: "Каждая характеристика от 8 до 15, дороже всего последние очки.",
  roll: "Сервер бросит 4d6 шесть раз, один раз на героя, и отбросит меньший кубик. Выпавшие числа разложите сами.",
};

const ABILS = ["str", "dex", "con", "int", "wis", "cha"];

export function emptyDraft(opts: BuilderOptions): Draft {
  return {
    name: "",
    class_id: "",
    origin_id: "",
    ability_method: opts.ability_methods[0] ?? "standard_array",
    abilities: Object.fromEntries(ABILS.map((a) => [a, null])),
    ability_picks: [],
    skills: [],
    equipment_choices: [],
    cantrips: [],
    spells: [],
    prepared: [],
    public_bio: "",
    private_backstory: "",
  };
}

export function draftFrom(obj: SavedHero, opts: BuilderOptions): Draft {
  const s = (obj.sheet ?? {}) as Record<string, unknown>;
  const base = emptyDraft(opts);
  const method = s.ability_method as Method | undefined;
  return {
    ...base,
    name: obj.name ?? "",
    class_id: (s.class_id as string) ?? "",
    origin_id: (s.origin_id as string) ?? "",
    ability_method: method && opts.ability_methods.includes(method) ? method : base.ability_method,
    abilities: { ...base.abilities, ...((s.abilities as Record<string, number>) ?? {}) },
    ability_picks: splitPicks((s.ability_choice as string[]) ?? [], opts.origins.find((o) => o.id === s.origin_id)),
    skills: (s.skills as string[]) ?? [],
    equipment_choices: ((s.equipment_choices as EquipChoice[]) ?? []).map((c) => ({ ...c, items: c.items ?? [] })),
    cantrips: (s.cantrips as string[]) ?? [],
    spells: (s.spells as string[]) ?? [],
    prepared: (s.prepared as string[]) ?? [],
    public_bio: obj.public_bio ?? "",
    private_backstory: obj.private_backstory ?? "",
  };
}

/** Тело запроса: пустые поля не шлём, чтобы сервер не спорил о незаполненном. */
export function toBody(d: Draft, rolls?: number[] | null): Record<string, unknown> {
  const abilities = Object.fromEntries(Object.entries(d.abilities).filter(([, v]) => v != null));
  return {
    name: d.name,
    ...(d.class_id ? { class_id: d.class_id } : {}),
    ...(d.origin_id ? { origin_id: d.origin_id } : {}),
    ability_method: d.ability_method,
    abilities,
    ability_choice: d.ability_picks.flat(),
    skills: d.skills,
    equipment_choices: d.equipment_choices,
    cantrips: d.cantrips,
    spells: d.spells,
    prepared: d.prepared,
    public_bio: d.public_bio,
    private_backstory: d.private_backstory,
    ...(rolls?.length ? { ability_rolls: rolls } : {}),
  };
}

/** Какие значения ещё можно поставить: стандартный набор и выпавшие броски раскладываются по разу. */
export function poolLeft(pool: number[], abilities: Record<string, number | null>, except: string): number[] {
  const left = [...pool];
  for (const [a, v] of Object.entries(abilities)) {
    if (a === except || v == null) continue;
    const i = left.indexOf(v);
    if (i >= 0) left.splice(i, 1);
  }
  return left;
}

export function pointsSpent(abilities: Record<string, number | null>, cost: Record<string, number>): number {
  return Object.values(abilities).reduce<number>((sum, v) => sum + (v == null ? cost["8"] ?? 0 : cost[String(v)] ?? 0), 0);
}

/** Выбор снаряжения по умолчанию — первый вариант каждого набора; оружие «любое» — первое подходящее. */
export function equipFor(cls: ClassOption | undefined, prev: EquipChoice[], opts: BuilderOptions): EquipChoice[] {
  if (!cls) return [];
  return cls.equipment_choices.map((alts, i) => {
    const had = prev.find((x) => x.choice === i);
    const option = had && had.option < alts.length ? had.option : 0;
    return { choice: i, option, items: weaponSlots(alts[option] ?? [], had?.option === option ? had.items : [], opts) };
  });
}

export function weaponSlots(bundle: EquipPart[], picked: string[], opts: BuilderOptions): string[] {
  const out: string[] = [];
  for (const part of bundle) {
    if (!part.any) continue;
    const list = weaponsOf(part.any, opts);
    for (let k = 0; k < (part.qty ?? 1); k++) out.push(picked[out.length] ?? list[0]?.[0] ?? "");
  }
  return out;
}

export function weaponsOf(group: string, opts: BuilderOptions): [string, string][] {
  return Object.entries(opts.weapons)
    .filter(([, w]) => (w.group ?? "").startsWith(group))
    .map(([id, w]) => [id, w.name] as [string, string])
    .sort((a, b) => a[1].localeCompare(b[1], "ru"));
}

const GROUP_RU: Record<string, string> = {
  simple: "простое оружие",
  martial: "воинское оружие",
  simple_melee: "простое рукопашное",
  simple_ranged: "простое дальнобойное",
  martial_melee: "воинское рукопашное",
  martial_ranged: "воинское дальнобойное",
};

export function partLabel(p: EquipPart): string {
  const qty = p.qty && p.qty > 1 ? `${p.qty} × ` : "";
  if (p.any) return `${qty}${GROUP_RU[p.any] ?? p.any} на выбор`;
  return qty + (p.name ?? p.other ?? p.item ?? "");
}

/** Сколько заклинаний выбрать: заговоры и известные — из класса, подготовленные — из живого листа. */
export function spellNeed(cls: ClassOption | undefined, preview: Preview | null) {
  const cs = cls?.spells;
  if (!cs) return null;
  const live = preview?.derived?.spellcasting?.needs;
  return {
    cantrips: live?.cantrips ?? cs.cantrips,
    spells: live?.spells ?? cs.known ?? 0,
    prepared: cs.mode === "known" ? 0 : (live?.prepared ?? null),
  };
}

/** Шаги конструктора и готов ли каждый: чтобы игрок видел, что осталось. */
export function steps(
  d: Draft,
  opts: BuilderOptions,
  preview: Preview | null = null,
): { id: string; label: string; done: boolean }[] {
  const cls = opts.classes.find((c) => c.id === d.class_id);
  const need = cls?.skills_choose?.count ?? 0;
  const origin = opts.origins.find((o) => o.id === d.origin_id);
  const sn = spellNeed(cls, preview);
  const spellStep = sn
    ? [
        {
          id: "spells",
          label: "Заклинания",
          done:
            d.cantrips.length === sn.cantrips &&
            (cls?.spells?.mode === "prepared" || d.spells.length === sn.spells) &&
            (sn.prepared === 0 || (sn.prepared != null && d.prepared.length === sn.prepared)),
        },
      ]
    : [];
  return [
    { id: "name", label: "Имя", done: !!d.name.trim() },
    { id: "class", label: "Класс", done: !!cls },
    { id: "origin", label: "Происхождение", done: !!d.origin_id },
    {
      id: "abilities",
      label: "Характеристики",
      done:
        Object.values(d.abilities).every((v) => v != null) &&
        (origin?.ability_groups ?? []).every((g, i) => (d.ability_picks[i]?.length ?? 0) === g.count),
    },
    { id: "skills", label: "Навыки", done: !!cls && d.skills.length === need },
    ...spellStep,
    { id: "gear", label: "Снаряжение", done: !!cls },
    { id: "story", label: "История", done: !!d.public_bio.trim() },
  ];
}

/** Герой кампании, как его отдаёт сервер своему игроку. */
export interface CampaignHero extends SavedHero {
  seat_id: string | null;
  status: string;
  reviewer?: "ai" | "master" | null;
  review_error?: string | null;
  review_comment?: string | null;
  class_name?: string | null;
  origin_name?: string | null;
  derived?: { hp_max?: number; ac?: number } | null;
}

/** Герой из профиля игрока. */
export interface LibraryHero extends SavedHero {
  class_name: string | null;
  origin_name: string | null;
  /** Мир, для которого собран герой: null — базовые правила D&D 5e. */
  pack_id: string | null;
  world_name: string | null;
  level: number;
  errors: string[];
  copies?: { campaign_id: string; campaign_name: string; character_id: string; status: string; level: number }[];
}

/** Мир для героя профиля: id null — базовые правила. */
export interface World {
  id: string | null;
  name: string;
}

export type BuilderMode = "campaign" | "premade" | "library";

/** Куда сохранять героя: у каждого режима свои адреса. */
/** asSeat — место ИИ-игрока: владелец собирает героя за него (этап 9). */
export function builderUrls(mode: BuilderMode, campaignId: string | undefined, id: string | undefined, asSeat?: string) {
  const base = `/api/campaigns/${campaignId}`;
  const q = asSeat ? `?as_seat=${encodeURIComponent(asSeat)}` : "";
  if (mode === "library")
    return {
      options: "/api/me/character-options",
      preview: "/api/me/character-preview",
      save: id ? `/api/me/characters/${id}` : "/api/me/characters",
      roll: id ? `/api/me/characters/${id}/roll-abilities` : null,
    };
  const coll = mode === "premade" ? "premades" : "characters";
  return {
    options: `${base}/character-options${q}`,
    preview: `${base}/character-preview${q}`,
    save: (id ? `${base}/${coll}/${id}` : `${base}/${coll}`) + q,
    roll: id && mode === "campaign" ? `${base}/characters/${id}/roll-abilities${q}` : null,
    submit: id ? `${base}/characters/${id}/submit${q}` : null,
  };
}

export const HERO_STATUS_RU: Record<string, string> = {
  draft: "черновик",
  submitted: "на проверке",
  approved: "в игре",
  active: "в игре",
  dead: "погиб",
  retired: "ушёл",
  premade: "готовый герой",
};

/** Выбор меняет метод: прежние числа к новому методу не подходят. */
export function withMethod(d: Draft, m: Method): Draft {
  const fill = m === "point_buy" ? 8 : null;
  return { ...d, ability_method: m, abilities: Object.fromEntries(ABILS.map((a) => [a, fill])) };
}

/** Сохранённый плоский выбор прибавок — обратно по группам происхождения. */
export function splitPicks(flat: string[], origin: OriginOption | undefined): string[][] {
  let i = 0;
  return (origin?.ability_groups ?? []).map((g) => {
    const part = flat.slice(i, i + g.count);
    i += g.count;
    return part;
  });
}

/** Что можно выбрать в группе: её список, без уже выбранного раньше, если группа этого требует. */
export function groupOptions(origin: OriginOption, picks: string[][], gi: number): string[] {
  const g = origin.ability_groups[gi];
  const prior = g.distinct_from_prior ? picks.slice(0, gi).flat() : [];
  return g.from.filter((a) => !prior.includes(a));
}
