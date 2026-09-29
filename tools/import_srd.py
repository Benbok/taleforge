"""Генератор данных базового пакета dnd5e-srd из базы 5e-bits (SRD 5.1, CC BY 4.0).

Скачивает JSON из репозитория 5e-bits/5e-database (зафиксированный коммит) в tools/.cache/
и пишет content/dnd5e-srd/data/{monsters,classes,races}.yaml.

    python tools/import_srd.py            # скачать (если нет в кэше) и сгенерировать
    python tools/import_srd.py --refresh  # перекачать JSON

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1")
by Wizards of the Coast LLC, licensed under CC BY 4.0. Data via 5e-bits/5e-database.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rules.dice import DiceError, parse  # noqa: E402
from app.rules.dnd5e.tables import CONDITIONS, DAMAGE_TYPES, SKILLS  # noqa: E402

SHA = "bce51b3958573819e3b842fbc0cd9524fe4bc2e1"
BASE_URL = f"https://raw.githubusercontent.com/5e-bits/5e-database/{SHA}/src/2014/en/"
FILES = ("Monsters", "Classes", "Levels", "Races", "Subraces", "Traits", "Equipment", "Proficiencies", "Features")
CACHE = Path(__file__).resolve().parent / ".cache"
DATA = ROOT / "content" / "dnd5e-srd" / "data"

ATTRIBUTION = (
    '# This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the\n'
    "# Coast LLC, licensed under CC BY 4.0. Данные: 5e-bits/5e-database, коммит " + SHA + ".\n"
    "# Файл сгенерирован tools/import_srd.py — не править руками, правьте генератор.\n"
)

# Сводка пропущенного: печатается в конце.
SKIPPED: Counter[str] = Counter()
SKIPPED_EXAMPLES: dict[str, list[str]] = {}


def skip(kind: str, where: str) -> None:
    SKIPPED[kind] += 1
    SKIPPED_EXAMPLES.setdefault(kind, [])
    if len(SKIPPED_EXAMPLES[kind]) < 5:
        SKIPPED_EXAMPLES[kind].append(where)


# --- Загрузка ---


def fetch(name: str, refresh: bool = False) -> Any:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{SHA[:12]}-5e-SRD-{name}.json"
    if refresh or not path.exists():
        url = f"{BASE_URL}5e-SRD-{name}.json"
        print(f"скачиваю {url}")
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 — фиксированный https-адрес
            path.write_bytes(r.read())
    return json.loads(path.read_text(encoding="utf-8"))


# --- Вывод YAML ---


class _Dumper(yaml.SafeDumper):
    pass


def _is_scalar(v: Any) -> bool:
    return not isinstance(v, (dict, list))


def _short(v: Any) -> bool:
    """Короткая коллекция скаляров пишется в строку: {str: 10, dex: 12}, [srd, beast]."""
    items = list(v.items()) if isinstance(v, dict) else list(v)
    flat = all(_is_scalar(x) for kv in items for x in (kv if isinstance(v, dict) else (kv,)))
    return flat and len(repr(v)) <= 110


def _repr_dict(d: _Dumper, data: dict) -> yaml.Node:
    return d.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=_short(data))


def _repr_list(d: _Dumper, data: list) -> yaml.Node:
    return d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=_short(data))


def _repr_str(d: _Dumper, data: str) -> yaml.Node:
    style = "|" if "\n" in data else None
    return d.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(dict, _repr_dict)
_Dumper.add_representer(list, _repr_list)
_Dumper.add_representer(str, _repr_str)


def write_yaml(name: str, header: str, kind: str, items: list[dict]) -> None:
    body = yaml.dump(
        {"kind": kind, "items": items}, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100000, indent=2
    )
    # Как в остальных файлах пакета: элементы списка items с отступом в два пробела.
    lines = body.splitlines()
    out = []
    in_items = False
    for line in lines:
        if line == "items:":
            in_items = True
            out.append(line)
            continue
        out.append(("  " + line) if in_items and line else line)
    (DATA / name).write_text(header + ATTRIBUTION + "\n".join(out) + "\n", encoding="utf-8")
    print(f"{name}: {len(items)} записей")


# --- Общие помощники ---


def snake(s: str) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def clean(d: dict) -> dict:
    """Убрать пустые поля: None, [], {}, ''."""
    return {k: v for k, v in d.items() if v not in (None, [], {}, "")}


def dice_ok(expr: str, where: str) -> str | None:
    e = expr.replace(" ", "")
    try:
        parse(e)
    except DiceError:
        skip("dice", f"{where}: {expr!r}")
        return None
    return e


def damage_key(name: str, where: str) -> str | None:
    k = name.strip().lower()
    if k in DAMAGE_TYPES:
        return k
    skip("damage_type", f"{where}: {name!r}")
    return None


def feet(v: str | int | bool) -> int | bool:
    if isinstance(v, (bool, int)):
        return v
    m = re.match(r"\s*(\d+)\s*ft", v)
    if not m:
        raise ValueError(v)
    return int(m.group(1))


def joined(desc: str | list[str]) -> str:
    return "\n".join(desc) if isinstance(desc, list) else desc


# --- Монстры ---

COLORS = {
    "black": ("чёрный", "чёрного"),
    "blue": ("синий", "синего"),
    "brass": ("латунный", "латунного"),
    "bronze": ("бронзовый", "бронзового"),
    "copper": ("медный", "медного"),
    "gold": ("золотой", "золотого"),
    "green": ("зелёный", "зелёного"),
    "red": ("красный", "красного"),
    "silver": ("серебряный", "серебряного"),
    "white": ("белый", "белого"),
}
AGES = {"young": "Молодой", "adult": "Взрослый", "ancient": "Древний"}
WERE = {
    "werebear": "Медведь-оборотень",
    "wereboar": "Кабан-оборотень",
    "wererat": "Крыса-оборотень",
    "weretiger": "Тигр-оборотень",
    "werewolf": "Волк-оборотень",
}
WERE_FORMS = {
    "human": "облик человека",
    "hybrid": "гибридный облик",
    "bear": "облик медведя",
    "boar": "облик кабана",
    "rat": "облик крысы",
    "tiger": "облик тигра",
    "wolf": "облик волка",
}

# Русские имена: по устоявшимся переводам D&D (Hobby World / dnd.su), где они известны.
RU: dict[str, str] = {
    "aboleth": "Аболет",
    "acolyte": "Послушник",
    "air-elemental": "Воздушный элементаль",
    "androsphinx": "Андросфинкс",
    "animated-armor": "Оживлённые доспехи",
    "ankheg": "Анхег",
    "ape": "Обезьяна",
    "archmage": "Архимаг",
    "assassin": "Ассасин",
    "awakened-shrub": "Пробуждённый куст",
    "awakened-tree": "Пробуждённое дерево",
    "axe-beak": "Топороклюв",
    "azer": "Азер",
    "baboon": "Павиан",
    "badger": "Барсук",
    "balor": "Балор",
    "bandit": "Бандит",
    "bandit-captain": "Капитан бандитов",
    "barbed-devil": "Шипастый дьявол",
    "basilisk": "Василиск",
    "bat": "Летучая мышь",
    "bearded-devil": "Бородатый дьявол",
    "behir": "Бехир",
    "berserker": "Берсерк",
    "black-bear": "Чёрный медведь",
    "black-pudding": "Чёрный пудинг",
    "blink-dog": "Мерцающий пёс",
    "blood-hawk": "Кровавый ястреб",
    "boar": "Кабан",
    "bone-devil": "Костяной дьявол",
    "brown-bear": "Бурый медведь",
    "bugbear": "Багбир",
    "bulette": "Булетт",
    "camel": "Верблюд",
    "cat": "Кошка",
    "centaur": "Кентавр",
    "chain-devil": "Цепной дьявол",
    "chimera": "Химера",
    "chuul": "Чуул",
    "clay-golem": "Глиняный голем",
    "cloaker": "Плащевик",
    "cloud-giant": "Облачный великан",
    "cockatrice": "Кокатрис",
    "commoner": "Обыватель",
    "constrictor-snake": "Удав",
    "couatl": "Коатль",
    "crab": "Краб",
    "crocodile": "Крокодил",
    "cult-fanatic": "Фанатик культа",
    "cultist": "Культист",
    "darkmantle": "Мракоплащ",
    "death-dog": "Пёс смерти",
    "deep-gnome-svirfneblin": "Глубинный гном (свирфнеблин)",
    "deer": "Олень",
    "deva": "Дэва",
    "dire-wolf": "Лютоволк",
    "djinni": "Джинн",
    "doppelganger": "Доппельгангер",
    "draft-horse": "Тягловая лошадь",
    "dragon-turtle": "Драконья черепаха",
    "dretch": "Дретч",
    "drider": "Драук",
    "drow": "Дроу",
    "druid": "Друид",
    "dryad": "Дриада",
    "duergar": "Дуэргар",
    "dust-mephit": "Пылевой мефит",
    "eagle": "Орёл",
    "earth-elemental": "Земляной элементаль",
    "efreeti": "Ифрит",
    "elephant": "Слон",
    "elk": "Лось",
    "erinyes": "Эриния",
    "ettercap": "Эттеркап",
    "ettin": "Эттин",
    "fire-elemental": "Огненный элементаль",
    "fire-giant": "Огненный великан",
    "flesh-golem": "Плотяной голем",
    "flying-snake": "Летающая змея",
    "flying-sword": "Летающий меч",
    "frog": "Лягушка",
    "frost-giant": "Ледяной великан",
    "gargoyle": "Горгулья",
    "gelatinous-cube": "Студенистый куб",
    "ghast": "Вурдалак",
    "ghost": "Привидение",
    "ghoul": "Упырь",
    "giant-ape": "Гигантская обезьяна",
    "giant-badger": "Гигантский барсук",
    "giant-bat": "Гигантская летучая мышь",
    "giant-boar": "Гигантский кабан",
    "giant-centipede": "Гигантская многоножка",
    "giant-constrictor-snake": "Гигантский удав",
    "giant-crab": "Гигантский краб",
    "giant-crocodile": "Гигантский крокодил",
    "giant-eagle": "Гигантский орёл",
    "giant-elk": "Гигантский лось",
    "giant-fire-beetle": "Гигантский огненный жук",
    "giant-frog": "Гигантская лягушка",
    "giant-goat": "Гигантский козёл",
    "giant-hyena": "Гигантская гиена",
    "giant-lizard": "Гигантская ящерица",
    "giant-octopus": "Гигантский осьминог",
    "giant-owl": "Гигантская сова",
    "giant-poisonous-snake": "Гигантская ядовитая змея",
    "giant-rat": "Гигантская крыса",
    "giant-rat-diseased": "Гигантская крыса (заразная)",
    "giant-scorpion": "Гигантский скорпион",
    "giant-sea-horse": "Гигантский морской конёк",
    "giant-shark": "Гигантская акула",
    "giant-spider": "Гигантский паук",
    "giant-toad": "Гигантская жаба",
    "giant-vulture": "Гигантский стервятник",
    "giant-wasp": "Гигантская оса",
    "giant-weasel": "Гигантская ласка",
    "giant-wolf-spider": "Гигантский паук-волк",
    "gibbering-mouther": "Бормочущий ротовик",
    "glabrezu": "Глабрезу",
    "gladiator": "Гладиатор",
    "gnoll": "Гнолл",
    "goat": "Козёл",
    "goblin": "Гоблин",
    "gorgon": "Горгон",
    "gray-ooze": "Серая слизь",
    "green-hag": "Зелёная карга",
    "grick": "Грик",
    "griffon": "Грифон",
    "grimlock": "Гримлок",
    "guard": "Стражник",
    "guardian-naga": "Нага-страж",
    "gynosphinx": "Гиносфинкс",
    "half-red-dragon-veteran": "Ветеран-полудракон (красный)",
    "harpy": "Гарпия",
    "hawk": "Ястреб",
    "hell-hound": "Адская гончая",
    "hezrou": "Хезроу",
    "hill-giant": "Холмовой великан",
    "hippogriff": "Гиппогриф",
    "hobgoblin": "Хобгоблин",
    "homunculus": "Гомункул",
    "horned-devil": "Рогатый дьявол",
    "hunter-shark": "Акула-охотник",
    "hydra": "Гидра",
    "hyena": "Гиена",
    "ice-devil": "Ледяной дьявол",
    "ice-mephit": "Ледяной мефит",
    "imp": "Бес",
    "invisible-stalker": "Невидимый охотник",
    "iron-golem": "Железный голем",
    "jackal": "Шакал",
    "killer-whale": "Косатка",
    "knight": "Рыцарь",
    "kobold": "Кобольд",
    "kraken": "Кракен",
    "lamia": "Ламия",
    "lemure": "Лемур",
    "lich": "Лич",
    "lion": "Лев",
    "lizard": "Ящерица",
    "lizardfolk": "Людоящер",
    "mage": "Маг",
    "magma-mephit": "Магмовый мефит",
    "magmin": "Магмин",
    "mammoth": "Мамонт",
    "manticore": "Мантикора",
    "marilith": "Марилит",
    "mastiff": "Мастиф",
    "medusa": "Медуза",
    "merfolk": "Мерфолк",
    "merrow": "Мерроу",
    "mimic": "Мимик",
    "minotaur": "Минотавр",
    "minotaur-skeleton": "Скелет минотавра",
    "mule": "Мул",
    "mummy": "Мумия",
    "mummy-lord": "Лорд мумий",
    "nalfeshnee": "Налфешни",
    "night-hag": "Ночная карга",
    "nightmare": "Кошмар",
    "noble": "Дворянин",
    "ochre-jelly": "Охряное желе",
    "octopus": "Осьминог",
    "ogre": "Огр",
    "ogre-zombie": "Зомби-огр",
    "oni": "Они",
    "orc": "Орк",
    "otyugh": "Отидж",
    "owl": "Сова",
    "owlbear": "Совомед",
    "panther": "Пантера",
    "pegasus": "Пегас",
    "phase-spider": "Фазовый паук",
    "pit-fiend": "Исчадие ямы",
    "planetar": "Планетар",
    "plesiosaurus": "Плезиозавр",
    "poisonous-snake": "Ядовитая змея",
    "polar-bear": "Белый медведь",
    "pony": "Пони",
    "priest": "Священник",
    "pseudodragon": "Псевдодракон",
    "purple-worm": "Лиловый червь",
    "quasit": "Квазит",
    "quipper": "Квиппер",
    "rakshasa": "Ракшас",
    "rat": "Крыса",
    "raven": "Ворон",
    "reef-shark": "Рифовая акула",
    "remorhaz": "Реморац",
    "rhinoceros": "Носорог",
    "riding-horse": "Ездовая лошадь",
    "roc": "Рух",
    "roper": "Ропер",
    "rug-of-smothering": "Удушающий ковёр",
    "rust-monster": "Ржавник",
    "saber-toothed-tiger": "Саблезубый тигр",
    "sahuagin": "Сахуагин",
    "salamander": "Саламандра",
    "satyr": "Сатир",
    "scorpion": "Скорпион",
    "scout": "Разведчик",
    "sea-hag": "Морская карга",
    "sea-horse": "Морской конёк",
    "shadow": "Тень",
    "shambling-mound": "Шаркающий курган",
    "shield-guardian": "Щитовой страж",
    "shrieker": "Визгун",
    "skeleton": "Скелет",
    "solar": "Солар",
    "specter": "Спектр",
    "spider": "Паук",
    "spirit-naga": "Нага-дух",
    "sprite": "Спрайт",
    "spy": "Шпион",
    "steam-mephit": "Паровой мефит",
    "stirge": "Стирга",
    "stone-giant": "Каменный великан",
    "stone-golem": "Каменный голем",
    "storm-giant": "Штормовой великан",
    "succubus-incubus": "Суккуб/инкуб",
    "swarm-of-bats": "Рой летучих мышей",
    "swarm-of-beetles": "Рой жуков",
    "swarm-of-centipedes": "Рой многоножек",
    "swarm-of-insects": "Рой насекомых",
    "swarm-of-poisonous-snakes": "Рой ядовитых змей",
    "swarm-of-quippers": "Рой квипперов",
    "swarm-of-rats": "Рой крыс",
    "swarm-of-ravens": "Рой воронов",
    "swarm-of-spiders": "Рой пауков",
    "swarm-of-wasps": "Рой ос",
    "tarrasque": "Тарраска",
    "thug": "Громила",
    "tiger": "Тигр",
    "treant": "Трент",
    "tribal-warrior": "Племенной воин",
    "triceratops": "Трицератопс",
    "troll": "Тролль",
    "tyrannosaurus-rex": "Тираннозавр",
    "unicorn": "Единорог",
    "vampire-vampire": "Вампир",
    "vampire-bat": "Вампир (облик летучей мыши)",
    "vampire-mist": "Вампир (облик тумана)",
    "vampire-spawn": "Отродье вампира",
    "veteran": "Ветеран",
    "violet-fungus": "Фиолетовый гриб",
    "vrock": "Врок",
    "vulture": "Стервятник",
    "warhorse": "Боевой конь",
    "warhorse-skeleton": "Скелет боевого коня",
    "water-elemental": "Водяной элементаль",
    "weasel": "Ласка",
    "wight": "Умертвие",
    "will-o-wisp": "Блуждающий огонёк",
    "winter-wolf": "Зимний волк",
    "wolf": "Волк",
    "worg": "Ворг",
    "wraith": "Призрак",
    "wyvern": "Виверна",
    "xorn": "Зорн",
    "zombie": "Зомби",
}


def ru_name(index: str) -> str:
    if index in RU:
        return RU[index]
    parts = index.split("-")
    if parts[-1] == "dragon" and parts[0] in AGES and parts[1] in COLORS:
        return f"{AGES[parts[0]]} {COLORS[parts[1]][0]} дракон"
    if parts[-1] == "wyrmling" and parts[0] in COLORS:
        return f"Вирмлинг {COLORS[parts[0]][1]} дракона"
    if parts[0] in WERE:
        return f"{WERE[parts[0]]} ({WERE_FORMS[parts[1]]})"
    raise KeyError(f"нет русского имени для монстра {index}")


SAVE_RE = re.compile(r"^Saving Throw: (\w+)$")
SKILL_RE = re.compile(r"^Skill: (.+)$")
REACH_RE = re.compile(r"reach (\d+) ft")
RANGE_RE = re.compile(r"range (\d+)(?:/(\d+))? ft")


def usage(u: dict | None) -> dict | None:
    """Перезарядка и ограничения: {recharge: 5} | {per_day: 3} | {recharge_after: [short, long]}."""
    if not u:
        return None
    t = u.get("type")
    if t == "recharge on roll":
        return {"recharge": u["min_value"]}
    if t == "per day":
        return {"per_day": u["times"]}
    if t == "recharge after rest":
        return {"recharge_after": list(u["rest_types"])}
    return {"text": json.dumps(u)}


def save_of(dc: dict | None) -> dict | None:
    if not dc:
        return None
    success = dc.get("success_type", "none")
    return {
        "ability": dc["dc_type"]["index"],
        "dc": dc["dc_value"],
        "success": success if success in ("half", "none") else "none",
    }


def damage_list(raw: list[dict], where: str) -> list[dict]:
    out = []
    for d in raw or []:
        if "choose" in d:
            opts = d["from"].get("options") or []
            if not opts:
                skip("damage_choose_empty", where)
                continue
            d = opts[0]
            skip("damage_choose_first", where)
        if "damage_dice" not in d or "damage_type" not in d:
            skip("damage_without_dice", where)
            continue
        dice = dice_ok(d["damage_dice"], where)
        dtype = damage_key(d["damage_type"]["index"], where)
        if dice and dtype:
            out.append({"dice": dice, "type": dtype})
    return out


def action_kind(desc: str, a: dict) -> str:
    head = desc.strip().split(":", 1)[0]
    if a.get("name") == "Multiattack" or "multiattack_type" in a:
        return "multiattack"
    if head in ("Melee Weapon Attack", "Melee or Ranged Weapon Attack"):
        return "melee_weapon"
    if head == "Ranged Weapon Attack":
        return "ranged_weapon"
    if head == "Melee Spell Attack":
        return "melee_spell"
    if head == "Ranged Spell Attack":
        return "ranged_spell"
    if a.get("dc"):
        return "save"
    return "other"


def multiattack_of(a: dict, keys: set[str], where: str) -> list[dict]:
    if a.get("multiattack_type") == "actions":
        entries = a.get("actions") or []
    elif a.get("multiattack_type") == "action_options":
        opts = a["action_options"]["from"]["options"]
        first = opts[0]
        entries = first["items"] if first.get("option_type") == "multiple" else [first]
        skip("multiattack_options_first", where)
    else:
        return []
    out = []
    for e in entries:
        n = e.get("count", 1)
        # «Claws» при действии «Claw», «Bite (Bat or Vampire Form Only)» при «Bite»: сводим к ключу действия.
        key = snake(re.sub(r"\s*\(.*?\)", "", e["action_name"]))
        if key not in keys and key.endswith("s") and key[:-1] in keys:
            key = key[:-1]
        ref: dict[str, Any] = {"action": key, "count": 1}
        if isinstance(n, int) or str(n).isdigit():
            ref["count"] = int(n)
        else:
            ref["count_text"] = str(n)  # гидра: «Number of Heads»
            skip("multiattack_count_text", f"{where}: {n}")
        out.append(ref)
    return out


def convert_action(a: dict, keys: set[str], where: str) -> dict:
    desc = a.get("desc", "")
    kind = action_kind(desc, a)
    rec: dict[str, Any] = {"key": snake(a["name"]), "name": a["name"], "kind": kind}
    src = a
    # Набор вариантов (дыхание металлических драконов, рык андросфинкса): берём первый, полный текст в description.
    if "options" in a or "attacks" in a:
        opts = a["options"]["from"]["options"] if "options" in a else a["attacks"]
        src = next((o for o in opts if o.get("damage")), opts[0])
        skip("action_options_first", where)
        if kind == "other" and src.get("dc"):
            rec["kind"] = kind = "save"
    if "attack_bonus" in a:
        rec["attack_bonus"] = int(a["attack_bonus"])
    if kind in ("melee_weapon", "melee_spell"):
        m = REACH_RE.search(desc)
        if m:
            rec["reach_ft"] = int(m.group(1))
    if kind in ("ranged_weapon", "ranged_spell", "melee_weapon"):
        m = RANGE_RE.search(desc)
        if m:
            rng = {"normal": int(m.group(1))}
            if m.group(2):
                rng["long"] = int(m.group(2))
            rec["range"] = rng
    rec["damage"] = damage_list(src.get("damage"), where)
    save = save_of(src.get("dc")) or next((save_of(d.get("dc")) for d in src.get("damage") or [] if d.get("dc")), None)
    rec["save"] = save
    if kind == "multiattack":
        rec["multiattack"] = multiattack_of(a, keys, where)
    rec["usage"] = usage(a.get("usage"))
    rec["description"] = desc
    return clean(rec)


def simple_entries(entries: list[dict] | None) -> list[dict]:
    out = []
    for e in entries or []:
        name = e["name"]
        out.append(clean({"name": name, "usage": usage(e.get("usage")), "description": e.get("desc", "")}))
    return out


def ac_note(first: dict) -> str | None:
    t = first["type"]
    if t == "armor":
        if first.get("armor"):
            return ", ".join(x["name"].lower() for x in first["armor"])
        return first.get("desc")
    if t == "natural":
        return "natural armor"
    if t == "spell":
        return f"with {first['spell']['name'].lower()}"
    if t == "condition":
        return f"while {first['condition']['name'].lower()}"
    return first.get("desc")


def damage_block(m: dict, field: str, kind: str, notes: list[dict]) -> list[str]:
    out = []
    for v in m[field]:
        k = v.strip().lower()
        if k in DAMAGE_TYPES:
            out.append(k)
        else:
            notes.append({"kind": kind, "text": v})
    return out


def behavior(m: dict, ctype: str, swarm: bool) -> dict:
    if ctype == "beast" and not swarm and m["challenge_rating"] <= 0.25 and m["intelligence"] <= 3:
        return {"profile": "cowardly", "flee_threshold": 0.5}
    return {"profile": "aggressive", "flee_threshold": 0.25}


def convert_monster(m: dict) -> dict:
    idx = m["index"]
    where = f"creature.{snake(idx)}"
    raw_type = m["type"].strip()
    swarm = raw_type.lower().startswith("swarm")
    ctype = "beast" if swarm else raw_type.lower()
    tags = ["srd", ctype]
    if swarm:
        tags.append("swarm")
    if m.get("subtype"):
        tags.append(snake(m["subtype"]))
    cr = m["challenge_rating"]
    cr = int(cr) if float(cr).is_integer() else float(cr)

    hp_dice = dice_ok(m["hit_points_roll"], where + " hp")
    speed = {}
    for k, v in m["speed"].items():
        speed[k] = feet(v)
    senses = {}
    for k, v in m["senses"].items():
        senses[k] = v if k == "passive_perception" else feet(v)

    saves, skills = {}, {}
    for p in m["proficiencies"]:
        name = p["proficiency"]["name"]
        if s := SAVE_RE.match(name):
            saves[s.group(1).lower()] = int(p["value"])
        elif s := SKILL_RE.match(name):
            key = snake(s.group(1))
            if key in SKILLS:
                skills[key] = int(p["value"])
            else:
                skip("skill", f"{where}: {name}")

    notes: list[dict] = []
    resist = damage_block(m, "damage_resistances", "resistance", notes)
    immune = damage_block(m, "damage_immunities", "immunity", notes)
    vulner = damage_block(m, "damage_vulnerabilities", "vulnerability", notes)
    cond = []
    for c in m["condition_immunities"]:
        k = c["index"] if isinstance(c, dict) else str(c).lower()
        if k in CONDITIONS:
            cond.append(k)
        else:
            skip("condition", f"{where}: {k}")

    action_keys = {snake(a["name"]) for a in m.get("actions") or []}
    ac0 = m["armor_class"][0]
    rec = {
        "id": where,
        "name": ru_name(idx),
        "status": "canon",
        "doc": "SRD 5.1: Monsters",
        "tags": tags,
        "srd_ref": {"type": "monster", "name": m["name"]},
        "size": m["size"].lower(),
        "creature_type": ctype,
        "alignment": m["alignment"],
        "cr": cr,
        "xp": int(m["xp"]),
        "ac": int(ac0["value"]),
        "ac_note": ac_note(ac0) if ac0["type"] != "dex" else None,
        "hp": clean({"average": int(m["hit_points"]), "dice": hp_dice}),
        "speed": speed,
        "abilities": {
            "str": m["strength"],
            "dex": m["dexterity"],
            "con": m["constitution"],
            "int": m["intelligence"],
            "wis": m["wisdom"],
            "cha": m["charisma"],
        },
        "saves": saves,
        "skills": skills,
        "senses": senses,
        "languages": m.get("languages") or None,
        "damage_resistances": resist,
        "damage_immunities": immune,
        "damage_vulnerabilities": vulner,
        "damage_notes": notes,
        "condition_immunities": cond,
        "traits": simple_entries(m.get("special_abilities")),
        "actions": [convert_action(a, action_keys, f"{where} {a['name']}") for a in m.get("actions") or []],
        "reactions": simple_entries(m.get("reactions")),
        "legendary_actions": simple_entries(m.get("legendary_actions")),
        "behavior": behavior(m, ctype, swarm),
    }
    out = clean(rec)
    # Мультиатака ссылается на ключи действий: проверяем, что такие есть.
    keys = {a["key"] for a in out.get("actions", [])}
    for a in out.get("actions", []):
        for ref in a.get("multiattack", []):
            if ref["action"] not in keys:
                skip("multiattack_unknown_action", f"{where}: {ref['action']}")
    return out


MONSTERS_HEADER = """\
# Монстры SRD 5.1 (Monsters, Creatures, NPCs). Имена — по-русски, srd_ref.name — английское имя SRD.
# Числа: cr (0.125 = 1/8), xp, ac (ac_note — источник КД), hp {average, dice}, скорость и чувства в футах.
# saves / skills — итоговые бонусы. damage_* — только чистые типы урона; условные («from nonmagical attacks»)
# лежат в damage_notes {kind, text}. Действия: kind melee_weapon | ranged_weapon | melee_spell | ranged_spell |
# save | multiattack | other; «Melee or Ranged Weapon Attack» — melee_weapon с reach_ft и range.
# usage — ограничение: {recharge: N} (перезарядка N–6), {per_day: N}, {recharge_after: [short, long]}.
# Если у действия несколько вариантов (дыхание, выбор урона, варианты мультиатаки) — в поля взят первый,
# полный текст — в description.
# behavior — эвристика генератора: звери (не рои) с cr <= 1/4 и int <= 3 — {cowardly, 0.5},
# все остальные — {aggressive, 0.25}. Пакет мира переопределяет по месту.
"""


def build_monsters(raw: list[dict]) -> list[dict]:
    return [convert_monster(m) for m in sorted(raw, key=lambda x: x["index"])]


# --- Классы ---

CLASS_RU = {
    "barbarian": "Варвар",
    "bard": "Бард",
    "cleric": "Жрец",
    "druid": "Друид",
    "fighter": "Воин",
    "monk": "Монах",
    "paladin": "Паладин",
    "ranger": "Следопыт",
    "rogue": "Плут",
    "sorcerer": "Чародей",
    "warlock": "Колдун",
    "wizard": "Волшебник",
}
ANY_CATEGORY = {
    "simple-weapons": "simple",
    "martial-weapons": "martial",
    "simple-melee-weapons": "simple_melee",
    "martial-melee-weapons": "martial_melee",
    "simple-ranged-weapons": "simple_ranged",
    "martial-ranged-weapons": "martial_ranged",
}
ARMOR_PROF = {
    "all-armor": ["light", "medium", "heavy"],
    "light-armor": ["light"],
    "medium-armor": ["medium"],
    "heavy-armor": ["heavy"],
    "shields": ["shield"],
}
WEAPON_PROF = {"simple-weapons": "simple", "martial-weapons": "martial"}


def pack_items() -> dict[str, str]:
    """Английское имя SRD (в нижнем регистре) → id записи пакета: оружие и доспехи."""
    out = {}
    for f in ("weapons.yaml", "armor.yaml"):
        doc = yaml.safe_load((DATA / f).read_text(encoding="utf-8"))
        for it in doc["items"]:
            out[it["srd_ref"]["name"].lower()] = it["id"]
    return out


class ItemMap:
    def __init__(self, equipment: list[dict]):
        self.by_name = pack_items()
        self.eq = {e["index"]: e for e in equipment}

    def item_id(self, eq_index: str) -> str | None:
        name = self.eq[eq_index]["name"].lower() if eq_index in self.eq else eq_index
        for cand in (name, re.sub(r" armor$", "", name)):
            if cand in self.by_name:
                return self.by_name[cand]
        return None

    def name(self, eq_index: str) -> str:
        return self.eq[eq_index]["name"] if eq_index in self.eq else eq_index

    def entry(self, eq_index: str, qty: int) -> dict:
        iid = self.item_id(eq_index)
        return {"item": iid, "qty": qty} if iid else {"other": ru_other(self.name(eq_index)), "qty": qty}


# Вещи без шаблона в пакете (наборы, фокусировки, инструменты): в листе героя они показываются как есть,
# поэтому имя сразу по-русски.
OTHER_RU = {
    "Arrow": "Стрела",
    "Burglar's Pack": "Набор взломщика",
    "Component pouch": "Мешочек с компонентами",
    "Crossbow bolt": "Арбалетный болт",
    "Diplomat's Pack": "Набор дипломата",
    "Dungeoneer's Pack": "Набор исследователя подземелий",
    "Entertainer's Pack": "Набор артиста",
    "Explorer's Pack": "Набор путешественника",
    "Lute": "Лютня",
    "Priest's Pack": "Набор священника",
    "Scholar's Pack": "Набор учёного",
    "Spellbook": "Книга заклинаний",
    "Thieves' Tools": "Воровские инструменты",
    "any other musical instrument": "любой другой музыкальный инструмент",
    "arcane focus": "магическая фокусировка",
    "druidic focus": "друидическая фокусировка",
    "holy symbol": "священный символ",
}


def ru_other(name: str | None) -> str | None:
    return OTHER_RU.get(name, name) if name else name


def bundle(opt: dict, im: ItemMap, where: str) -> list[dict]:
    """Одна альтернатива выбора → список (набор) записей {item|any|other, qty}."""
    t = opt.get("option_type")
    if t == "counted_reference":
        return [im.entry(opt["of"]["index"], int(opt.get("count", 1)))]
    if t == "multiple":
        return [e for sub in opt["items"] for e in bundle(sub, im, where)]
    if t == "choice":
        ch = opt["choice"]
        src = ch["from"]
        n = int(ch.get("choose", 1))
        if src.get("option_set_type") == "equipment_category":
            cat = src["equipment_category"]["index"]
            if cat in ANY_CATEGORY:
                return [{"any": ANY_CATEGORY[cat], "qty": n}]
            return [{"other": ru_other(ch.get("desc") or src["equipment_category"]["name"]), "qty": n}]
        skip("equipment_nested_choice", f"{where}: {ch.get('desc')}")
        return [{"other": ru_other(ch.get("desc", "?")), "qty": n}]
    skip("equipment_option", f"{where}: {t}")
    return []


def starting_equipment(c: dict, im: ItemMap) -> dict:
    fixed, other = [], []
    for e in c.get("starting_equipment") or []:
        ent = im.entry(e["equipment"]["index"], int(e.get("quantity", 1)))
        if "item" in ent:
            fixed.append(ent)
        else:
            other.append(ent["other"] if ent["qty"] == 1 else f"{ent['other']} ({ent['qty']})")
    choices = []
    for opt in c.get("starting_equipment_options") or []:
        src = opt["from"]
        where = f"class.{c['index']}"
        if src.get("option_set_type") == "options_array":
            choices.append([bundle(o, im, where) for o in src["options"]])
        elif src.get("option_set_type") == "equipment_category":
            cat = src["equipment_category"]["index"]
            n = int(opt.get("choose", 1))
            other = {"other": ru_other(opt.get("desc")), "qty": n}
            alt = {"any": ANY_CATEGORY[cat], "qty": n} if cat in ANY_CATEGORY else other
            choices.append([[alt]])
        else:
            skip("equipment_option_set", f"{where}: {opt.get('desc')}")
    return clean({"fixed": fixed, "choices": choices, "other": other})


def class_proficiencies(c: dict, profs: dict[str, dict], im: ItemMap) -> dict:
    armor, weapons, tools = [], [], []
    for p in c["proficiencies"]:
        i = p["index"]
        if i.startswith("saving-throw-"):
            continue
        if i in ARMOR_PROF:
            armor += ARMOR_PROF[i]
        elif i in WEAPON_PROF:
            weapons.append(WEAPON_PROF[i])
        else:
            ref = (profs.get(i) or {}).get("reference", {}).get("url", "")
            eq = ref.rsplit("/", 1)[-1] if "/equipment/" in ref else None
            iid = im.item_id(eq) if eq else None
            if iid and profs[i]["type"] == "Weapons":
                weapons.append(iid)
            elif profs.get(i, {}).get("type") in ("Artisan's Tools", "Other", "Musical Instruments", "Gaming Sets"):
                tools.append(snake(profs[i]["name"]))
            else:
                skip("class_proficiency", f"class.{c['index']}: {i}")
    out = {"armor": armor, "weapons": weapons, "tools": tools}
    for pc in c["proficiency_choices"]:
        opts = pc["from"].get("options") or []
        idx = [o.get("item", {}).get("index", "") for o in opts]
        if idx and all(x.startswith("skill-") for x in idx):
            continue
        out["tools_choose"] = {"count": int(pc["choose"]), "text": pc.get("desc", "")}
    return clean(out)


def skills_choose(c: dict) -> dict | None:
    for pc in c["proficiency_choices"]:
        opts = pc["from"].get("options") or []
        idx = [o.get("item", {}).get("index", "") for o in opts]
        if idx and all(x.startswith("skill-") for x in idx):
            keys = [snake(x.removeprefix("skill-")) for x in idx]
            for k in keys:
                if k not in SKILLS:
                    skip("skill", f"class.{c['index']}: {k}")
            return {"count": int(pc["choose"]), "from": [k for k in keys if k in SKILLS]}
    return None


def normalize_specific(cs: dict) -> dict:
    out = {}
    for k, v in (cs or {}).items():
        if isinstance(v, dict) and set(v) == {"dice_count", "dice_value"}:
            out[k] = f"{v['dice_count']}d{v['dice_value']}"
        else:
            out[k] = v
    return out


def level_row(lv: dict, caster: bool, warlock: bool) -> dict:
    row: dict[str, Any] = {
        "level": lv["level"],
        "pb": lv["prof_bonus"],
        "features": [snake(f["index"]) for f in lv.get("features") or []],
    }
    sc = lv.get("spellcasting")
    if caster and sc:
        slots = [int(sc.get(f"spell_slots_level_{i}", 0)) for i in range(1, 10)]
        if warlock:
            used = [(i + 1, n) for i, n in enumerate(slots) if n]
            if used:
                row["pact_slots"], row["pact_slot_level"] = used[0][1], used[0][0]
        else:
            row["slots"] = slots
        if sc.get("cantrips_known"):
            row["cantrips"] = sc["cantrips_known"]
        if sc.get("spells_known"):
            row["spells_known"] = sc["spells_known"]
    if lv.get("ability_score_bonuses"):
        row["asi_total"] = lv["ability_score_bonuses"]
    row["class_specific"] = normalize_specific(lv.get("class_specific"))
    return {k: v for k, v in row.items() if k == "features" or v not in (None, [], {}, "")}


CLASSES_HEADER = """\
# Классы SRD 5.1 (без подклассов). hit_die — строкой, как в пакете мира. levels — таблица класса по уровням:
# pb (бонус мастерства), features (ключи из features ниже), slots (ячейки 1–9 круга, для заклинателей),
# pact_slots / pact_slot_level (колдун), cantrips, spells_known, asi_total (сколько раз к этому уровню
# получено «Увеличение характеристик»), class_specific — числа класса из таблицы (ярость, скрытая атака, ци...).
# starting_equipment: fixed — всегда; choices — список выборов, каждый выбор — список альтернатив, каждая
# альтернатива — набор (список) записей {item: <id пакета>, qty} | {any: simple|martial|simple_melee|
# martial_melee, qty} | {other: <имя вещи вне пакета по-русски>, qty}; other — прочее снаряжение.
# features: умения класса (не подкласса); parent — у вариантов выбора (стиль боя, воззвания, метамагия).
"""


def build_classes(raw: dict[str, Any]) -> list[dict]:
    im = ItemMap(raw["Equipment"])
    profs = {p["index"]: p for p in raw["Proficiencies"]}
    levels = [lv for lv in raw["Levels"] if "subclass" not in lv]
    features = [f for f in raw["Features"] if "subclass" not in f]
    out = []
    for c in raw["Classes"]:
        ci = c["index"]
        caster = "spellcasting" in c
        warlock = ci == "warlock"
        rows = sorted((lv for lv in levels if lv["class"]["index"] == ci), key=lambda x: x["level"])
        feats = sorted(
            (f for f in features if f["class"]["index"] == ci), key=lambda f: (f["level"], "parent" in f, f["index"])
        )
        rec = {
            "id": f"class.{snake(ci)}",
            "name": CLASS_RU[ci],
            "status": "canon",
            "doc": "SRD 5.1: Classes",
            "tags": ["class", "srd"],
            "srd_ref": {"type": "class", "name": c["name"]},
            "hit_die": f"d{c['hit_die']}",
            "saving_throws": [s["index"] for s in c["saving_throws"]],
            "proficiencies": class_proficiencies(c, profs, im),
            "skills_choose": skills_choose(c),
            "starting_equipment": starting_equipment(c, im),
            "spellcasting": {"ability": c["spellcasting"]["spellcasting_ability"]["index"]} if caster else None,
            "levels": [level_row(lv, caster, warlock) for lv in rows],
            "features": [
                clean(
                    {
                        "key": snake(f["index"]),
                        "name": f["name"],
                        "level": f["level"],
                        "parent": snake(f["parent"]["index"]) if f.get("parent") else None,
                        "description": joined(f["desc"]),
                    }
                )
                for f in feats
            ],
        }
        if len(rec["levels"]) != 20:
            skip("class_levels_not_20", f"{ci}: {len(rec['levels'])}")
        keys = {f["key"] for f in rec["features"]}
        for row in rec["levels"]:
            for k in row["features"]:
                if k not in keys:
                    skip("level_feature_unknown", f"{ci}: {k}")
        out.append(clean(rec))
    return out


# --- Расы ---

RACE_IDS = {
    "hill-dwarf": ("origin.dwarf_hill", "Холмовой дварф"),
    "high-elf": ("origin.elf_high", "Высший эльф"),
    "lightfoot-halfling": ("origin.halfling_lightfoot", "Легконогий полурослик"),
    "human": ("origin.human", "Человек"),
    "dragonborn": ("origin.dragonborn", "Драконорождённый"),
    "rock-gnome": ("origin.gnome_rock", "Скальный гном"),
    "half-elf": ("origin.half_elf", "Полуэльф"),
    "half-orc": ("origin.half_orc", "Полуорк"),
    "tiefling": ("origin.tiefling", "Тифлинг"),
}
RESIST_RE = re.compile(r"resistance (?:to|against) (\w+) damage")

RACES_HEADER = """\
# Расы SRD 5.1 как происхождения героя: подраса — отдельная запись, в неё слиты прибавки и черты базовой расы.
# srd_ref.name — английское имя расы SRD (Dwarf, Elf...), srd_subrace — имя подрасы. ability_bonuses — фиксированные
# прибавки {характеристика: число}; ability_choose — прибавки на выбор игрока (полуэльф).
# languages — английские названия; languages_choose — сколько языков выбрать дополнительно.
# proficiencies: skills / weapons (id пакета) / tools, *_choose — выбор. darkvision — футы.
# features — черты расы (английский текст SRD); options — варианты выбора (драконье происхождение).
"""


def build_races(raw: dict[str, Any]) -> list[dict]:
    im = ItemMap(raw["Equipment"])
    profs = {p["index"]: p for p in raw["Proficiencies"]}
    traits = {t["index"]: t for t in raw["Traits"]}
    subraces = {s["race"]["index"]: s for s in raw["Subraces"]}
    out = []
    for race in raw["Races"]:
        sub = subraces.get(race["index"])
        key = sub["index"] if sub else race["index"]
        rid, ru = RACE_IDS[key]
        bonuses: dict[str, int] = {}
        for b in race["ability_bonuses"] + (sub["ability_bonuses"] if sub else []):
            a = b["ability_score"]["index"]
            bonuses[a] = bonuses.get(a, 0) + int(b["bonus"])
        trait_refs = race["traits"] + (sub["racial_traits"] if sub else [])
        tr = [traits[t["index"]] for t in trait_refs]

        skills, weapons, tools = [], [], []
        choose: dict[str, Any] = {}
        languages = [lang["name"] for lang in race["languages"]]
        lang_choose = 0
        if race.get("language_options"):
            lang_choose += int(race["language_options"]["choose"])
        for t in tr:
            for p in t.get("proficiencies") or []:
                i = p["index"]
                if i.startswith("skill-"):
                    skills.append(snake(i.removeprefix("skill-")))
                    continue
                ref = (profs.get(i) or {}).get("reference", {}).get("url", "")
                eq = ref.rsplit("/", 1)[-1] if "/equipment/" in ref else None
                iid = im.item_id(eq) if eq else None
                if iid:
                    weapons.append(iid)
                elif i in WEAPON_PROF:
                    weapons.append(WEAPON_PROF[i])
                else:
                    tools.append(snake(p["name"]))
            pc = t.get("proficiency_choices")
            if pc:
                idx = [o["item"]["index"] for o in pc["from"]["options"]]
                if all(x.startswith("skill-") for x in idx):
                    choose["skills_choose"] = {
                        "count": int(pc["choose"]),
                        "from": [snake(x.removeprefix("skill-")) for x in idx],
                    }
                else:
                    choose["tools_choose"] = {
                        "count": int(pc["choose"]),
                        "from": [snake(o["item"]["name"]) for o in pc["from"]["options"]],
                    }
            if t.get("language_options"):
                lang_choose += int(t["language_options"]["choose"])

        resist = []
        for t in tr:
            for m in RESIST_RE.finditer(joined(t["desc"])):
                k = m.group(1).lower()
                if k in DAMAGE_TYPES and k not in resist:
                    resist.append(k)

        features = []
        for t in tr:
            f: dict[str, Any] = {"key": snake(t["index"]), "name": t["name"], "description": joined(t["desc"])}
            ts = t.get("trait_specific") or {}
            if "subtrait_options" in ts:
                opts = []
                for o in ts["subtrait_options"]["from"]["options"]:
                    st = traits[o["item"]["index"]]
                    sp = st.get("trait_specific") or {}
                    bw = sp.get("breath_weapon") or {}
                    aoe = bw.get("area_of_effect") or {}
                    opts.append(
                        clean(
                            {
                                "key": snake(st["index"]),
                                "name": st["name"],
                                "damage_type": (sp.get("damage_type") or {}).get("index"),
                                "breath": clean(
                                    {
                                        "area": aoe.get("type"),
                                        "size_ft": aoe.get("size"),
                                        "save": (bw.get("dc") or {}).get("dc_type", {}).get("index"),
                                    }
                                ),
                            }
                        )
                    )
                f["options"] = opts
            if "spell_options" in ts:
                f["spell_choose"] = {
                    "count": int(ts["spell_options"]["choose"]),
                    "from": [o["item"]["name"] for o in ts["spell_options"]["from"]["options"]],
                }
            features.append(f)

        rec = {
            "id": rid,
            "name": ru,
            "status": "canon",
            "doc": "SRD 5.1: Races",
            "tags": ["race", "srd"],
            "srd_ref": {"type": "race", "name": race["name"]},
            "srd_subrace": sub["name"] if sub else None,
            "size": race["size"].lower(),
            "speed": int(race["speed"]),
            "ability_bonuses": bonuses,
            "ability_choose": None,
            "languages": languages,
            "languages_choose": lang_choose or None,
            "proficiencies": clean({"skills": skills, "weapons": weapons, "tools": tools} | choose),
            "darkvision": 60 if any(t["index"] == "darkvision" for t in tr) else None,
            "damage_resistances": resist,
            "features": features,
        }
        abo = race.get("ability_bonus_options")
        if abo:
            opts = abo["from"]["options"]
            allowed = {o["ability_score"]["index"] for o in opts}
            rec["ability_choose"] = {
                "count": int(abo["choose"]),
                "bonus": int(opts[0]["bonus"]),
                "exclude": [a for a in ("str", "dex", "con", "int", "wis", "cha") if a not in allowed],
            }
        out.append(clean(rec) | {"features": features})  # ядро требует features, у человека он пуст
    return out


# --- Точка входа ---


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="перекачать JSON, даже если он есть в кэше")
    args = ap.parse_args(argv)
    raw = {name: fetch(name, args.refresh) for name in FILES}

    write_yaml("monsters.yaml", MONSTERS_HEADER, "creature_template", build_monsters(raw["Monsters"]))
    write_yaml("classes.yaml", CLASSES_HEADER, "class", build_classes(raw))
    write_yaml("races.yaml", RACES_HEADER, "origin", build_races(raw))

    if SKIPPED:
        print("\nпропущено / упрощено:")
        for k, n in sorted(SKIPPED.items()):
            print(f"  {k}: {n}  (напр.: {'; '.join(SKIPPED_EXAMPLES[k][:3])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
