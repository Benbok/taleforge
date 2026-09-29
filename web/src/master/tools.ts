import type { Envelope } from "../lib/types";
import { useGame } from "../stores/game";

/** Поле формы инструмента: как его описывает сервер (app/core/master_panel.py). */
export interface ToolField {
  name: string;
  type: string;
  many: boolean;
  required: boolean;
  nullable: boolean;
  default: unknown;
  description: string;
  options: string[] | null;
  min: number | null;
  max: number | null;
  max_length: number | null;
}

export interface ToolSpec {
  name: string;
  description: string;
  group: string;
  mutating: boolean;
  fields: ToolField[];
}

export interface MasterPanelData {
  tools: ToolSpec[];
  labels: Record<string, string>;
  has_plot: boolean;
}

export interface ToolResult {
  ok: boolean;
  result?: Record<string, unknown>;
  error?: string;
  plot_clock?: string[];
}

export const TOOL_RU: Record<string, string> = {
  get_scene: "Сцена целиком",
  get_character: "Лист героя",
  lookup_template: "Найти шаблон",
  roll_check: "Проверка или спасбросок",
  resolve_attack: "Атака",
  death_save: "Спасбросок от смерти",
  apply_hazard: "Опасность среды",
  apply_effect: "Наложить эффект",
  remove_effect: "Снять эффект",
  use_item: "Применить предмет",
  give_item: "Выдать предмет",
  take_item: "Забрать предмет",
  equip_item: "Надеть или снять",
  spawn_entity: "Выставить существо",
  update_entity: "Изменить сущность",
  create_location: "Новая локация",
  move: "Переместить героев",
  reveal_knowledge: "Открыть знания",
  learn_fact: "Герои узнали факт",
  set_scene_mode: "Бой или свободный режим",
  advance_time: "Сдвинуть время",
  rest: "Отдых",
  grant_level: "Новый уровень",
  cross_threshold: "Порог: вторая раса",
  whisper: "Шёпот игроку",
  cancel_action: "Отказать в действии",
  auto_success: "Успех без броска",
  review_character: "Проверка героя",
  get_plot: "Каркас целиком",
  advance_plot: "Отметить узел сюжета",
  plot_reveal: "Тайна раскрыта",
  end_act: "Закрыть акт",
  develop: "Развернуть набросок",
  threat_tick: "Шаг угрозы",
};

export const FIELD_RU: Record<string, string> = {
  character_id: "Персонаж",
  character_ids: "Персонажи",
  target_id: "Цель",
  attacker_id: "Кто атакует",
  entity_id: "Сущность",
  subject_id: "О ком или о чём",
  location_id: "Куда",
  inventory_id: "Предмет",
  item_template_id: "Шаблон предмета",
  effect_template_id: "Эффект",
  effect_id: "Наложенный эффект",
  hazard_template_id: "Опасность",
  creature_template_id: "Шаблон существа",
  template_id: "Шаблон локации",
  stat: "Навык или характеристика",
  kind: "Вид",
  difficulty: "Сложность",
  reason: "Причина",
  attack: "Атака",
  height_ft: "Высота, футов",
  duration_value: "Длительность",
  duration_unit: "Единица",
  qty: "Количество",
  display_name: "Своё название",
  name: "Имя",
  count: "Сколько",
  zone: "Зона",
  attitude: "Отношение",
  description: "Описание для игроков",
  mood: "Настроение",
  note: "Пометка",
  fled: "Сбежал",
  make_current: "Сделать текущей сценой",
  level: "Уровень знаний",
  fact: "Факт",
  mode: "Режим",
  participants: "Участники боя",
  amount: "Сколько",
  unit: "Единица",
  spend_hit_dice: "Потратить костей хитов",
  text: "Текст",
  approve: "Одобрить",
  comment: "Комментарий игроку",
  secret_link: "Тайная связь с сюжетом",
  hook_ref: "Привязка к каркасу",
  equipped: "Надето",
  query: "Слова для поиска",
  node_id: "Узел",
  result: "Итог",
  outcome: "Чем кончилось",
  reveal_id: "Тайна",
  how: "Как раскрылась",
  sketch_id: "Набросок",
  details: "Детали",
  here: "Отряд уже здесь",
  antagonist_id: "Антагонист",
};

// подписи для значений перечислений, которых нет в подписях сервера
export const VALUE_RU: Record<string, string> = {
  check: "проверка",
  save: "спасбросок",
  free: "свободный режим",
  combat: "бой",
  round: "раунды",
  minute: "минуты",
  hour: "часы",
  day: "дни",
  short: "короткий",
  long: "продолжительный",
  done: "случился",
  skipped: "обойдён",
  creature_template: "существа",
  item_template: "предметы",
  effect_template: "эффекты и состояния",
  hazard_template: "опасности",
  location_template: "места",
  dc_scale: "сложности",
  faction: "фракции",
  lore_fact: "факты мира",
  class: "классы",
  origin: "происхождения",
};

export type Values = Record<string, string | string[] | boolean>;

const LONG_TEXT = new Set(["text", "description", "details", "outcome", "comment", "secret_link", "how", "fact", "note", "reason"]);

export function isLongText(f: ToolField): boolean {
  return f.type === "string" && !f.options && (LONG_TEXT.has(f.name) || (f.max_length ?? 0) > 500);
}

export function labelOf(labels: Record<string, string>, v: string): string {
  return labels[v] ?? VALUE_RU[v] ?? v;
}

/** Начальные значения формы: значение по умолчанию схемы, поверх — подстановка (из вкладки «Шаблоны» или «Игроки»). */
export function initialValues(tool: ToolSpec, prefill: Values = {}): Values {
  const out: Values = {};
  for (const f of tool.fields) {
    if (f.many) out[f.name] = [];
    else if (f.type === "boolean") out[f.name] = f.nullable ? "" : f.default === true;
    else out[f.name] = f.default == null ? "" : String(f.default);
  }
  return { ...out, ...prefill };
}

/** Чего не хватает, по-русски. Пусто — форму можно отправлять. */
export function problems(tool: ToolSpec, v: Values): string[] {
  const out: string[] = [];
  for (const f of tool.fields) {
    const x = v[f.name];
    const empty = Array.isArray(x) ? x.length === 0 : x === "" || x === undefined;
    const title = FIELD_RU[f.name] ?? f.name;
    if (f.required && f.type !== "boolean" && empty) out.push(`заполните «${title}»`);
    if (f.type === "integer" && !empty && typeof x === "string") {
      const n = Number(x);
      if (!Number.isInteger(n)) out.push(`«${title}»: нужно целое число`);
      else if (f.min != null && n < f.min) out.push(`«${title}»: не меньше ${f.min}`);
      else if (f.max != null && n > f.max) out.push(`«${title}»: не больше ${f.max}`);
    }
  }
  return out;
}

/** Аргументы вызова: пустые необязательные поля не отправляются, числа — числами. */
export function buildArgs(tool: ToolSpec, v: Values): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  for (const f of tool.fields) {
    const x = v[f.name];
    if (Array.isArray(x)) {
      if (x.length || f.required) args[f.name] = x;
    } else if (typeof x === "boolean") {
      args[f.name] = x;
    } else if (x === "" || x === undefined) {
      continue;
    } else if (f.type === "boolean") {
      args[f.name] = x === "true";
    } else if (f.type === "integer") {
      args[f.name] = Number(x);
    } else {
      args[f.name] = x.trim();
    }
  }
  return args;
}

// --- вызов инструмента через соединение игры ---

const waiting = new Map<string, { resolve: (r: ToolResult) => void; timer: ReturnType<typeof setTimeout> }>();
let counter = 0;
export const CALL_TIMEOUT_MS = 30000;

/** Вызывает инструмент от места мастера. Ответ приходит событием master.tool.result с тем же request_id. */
export function callTool(name: string, args: Record<string, unknown>): Promise<ToolResult> {
  const sock = useGame.getState().socket;
  const request_id = `m${Date.now().toString(36)}${(counter++).toString(36)}`;
  return new Promise((resolve, reject) => {
    if (!sock || !sock.send("master.tool", { tool: name, args, request_id })) {
      reject(new Error("нет связи с сервером: дождитесь переподключения"));
      return;
    }
    const timer = setTimeout(() => {
      waiting.delete(request_id);
      reject(new Error("сервер не ответил за 30 секунд; проверьте журнал, прежде чем повторять"));
    }, CALL_TIMEOUT_MS);
    waiting.set(request_id, { resolve, timer });
  });
}

/** Подхватывает ответ сервера на вызов. Возвращает true, если событие было ответом на наш вызов. */
export function resolveToolResult(e: Envelope): boolean {
  if (e.type !== "master.tool.result") return false;
  const id = String((e.payload as { request_id?: string }).request_id ?? "");
  const w = waiting.get(id);
  if (!w) return false;
  clearTimeout(w.timer);
  waiting.delete(id);
  w.resolve(e.payload as unknown as ToolResult);
  return true;
}
