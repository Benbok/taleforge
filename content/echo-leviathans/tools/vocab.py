#!/usr/bin/env python3
"""Собирает словарь, который реально используется в данных: op, события on, ключи if, цели target/set.
Результат — ENGINE_VOCAB.md: то, что движок должен понимать, чтобы исполнить пакет."""

import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from validate import ROOT, load  # noqa: E402

ops, ons, ifs, targets, customs = (collections.Counter() for _ in range(5))


def walk(o):
    if isinstance(o, dict):
        if "op" in o:
            ops[o["op"]] += 1
            if "target" in o and isinstance(o["target"], str):
                targets[f"{o['op']}: {o['target']}"] += 1
            if o["op"] == "custom":
                customs[o.get("need", "(need не указан)")] += 1
        if "on" in o and isinstance(o["on"], str) and "do" in o:
            ons[o["on"]] += 1
        for k in ("if", "adv_if", "dis_if"):
            if isinstance(o.get(k), dict):
                for kk in o[k]:
                    ifs[kk] += 1
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


for p in sorted((ROOT / "data").rglob("*.yaml")):
    walk((load(p.read_text()) or {}).get("items"))


def table(title, c):
    rows = "\n".join(f"| `{k}` | {n} |" for k, n in sorted(c.items(), key=lambda x: (-x[1], str(x[0]))))
    return f"## {title}\n\n| Значение | Раз |\n|---|---|\n{rows}\n"


out = [
    "# Словарь движка (сгенерирован tools/vocab.py)\n",
    "Всё, что встречается в данных пакета. Движок должен поддерживать каждую строку, иначе запись не исполнится. "
    "`custom` — механики, которые движку ещё предстоит поддержать (в живую игру не идут).\n",
    table("Операции op", ops),
    table("События триггеров on", ons),
    table("Ключи условий if / adv_if / dis_if", ifs),
    table("Цели target у операций", targets),
    table("Нужно движку (need у op: custom)", customs),
]
(ROOT / "ENGINE_VOCAB.md").write_text("\n".join(out))
print(
    len(ops),
    "ops;",
    len(ons),
    "events;",
    len(ifs),
    "if-keys;",
    len(targets),
    "targets;",
    sum(customs.values()),
    "custom",
)
