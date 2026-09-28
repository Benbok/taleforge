#!/usr/bin/env python3
"""Проверка пакета: схема каждой записи, уникальность id, ссылки *_ref / *_refs."""

import pathlib
import re
import sys

import jsonschema
import yaml


class Loader(yaml.SafeLoader):
    """YAML 1.2-style booleans: only true/false, so keys like `on` stay strings."""


Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load(text):
    return yaml.load(text, Loader=Loader)


ROOT = pathlib.Path(__file__).resolve().parent.parent
schema = load((ROOT / "schema/schema.yaml").read_text())


def main():
    global errors, ids, refs, counts

    errors, ids, refs, counts = [], {}, [], {}

    def schema_for(kind):
        k = schema["kinds"].get(kind)
        if k is None:
            return None
        s = {"allOf": [schema["common"], {"type": "object", **k}], "definitions": schema["definitions"]}
        return s

    def collect_refs(obj, where):
        if isinstance(obj, dict):
            for key, v in obj.items():
                if isinstance(key, str) and key.endswith("_ref") and isinstance(v, str):
                    refs.append((v, where))
                elif isinstance(key, str) and key.endswith("_refs") and isinstance(v, list):
                    refs.extend((x, where) for x in v if isinstance(x, str))
                else:
                    collect_refs(v, where)
        elif isinstance(obj, list):
            for v in obj:
                collect_refs(v, where)

    for path in sorted((ROOT / "data").rglob("*.yaml")):
        rel = path.relative_to(ROOT)
        try:
            doc = load(path.read_text())
        except yaml.YAMLError as e:
            errors.append(f"{rel}: YAML: {e}")
            continue
        if not isinstance(doc, dict) or "kind" not in doc or "items" not in doc:
            errors.append(f"{rel}: нужен {{kind, items}}")
            continue
        kind = doc["kind"]
        sch = schema_for(kind)
        if sch is None:
            errors.append(f"{rel}: неизвестный kind {kind}")
            continue
        for i, rec in enumerate(doc["items"] or []):
            rid = rec.get("id", f"#{i}") if isinstance(rec, dict) else f"#{i}"
            for err in jsonschema.Draft7Validator(sch).iter_errors(rec):
                errors.append(f"{rel}: {rid}: {'/'.join(map(str, err.path))} {err.message}")
            if rid in ids:
                errors.append(f"{rel}: дубликат id {rid} (уже в {ids[rid]})")
            ids[rid] = rel
            counts[kind] = counts.get(kind, 0) + 1
            collect_refs(rec, f"{rel}: {rid}")

    SRD_CONDITIONS = {
        "blinded",
        "charmed",
        "deafened",
        "exhaustion",
        "frightened",
        "grappled",
        "incapacitated",
        "invisible",
        "paralyzed",
        "petrified",
        "poisoned",
        "prone",
        "restrained",
        "stunned",
        "unconscious",
        "surprised",
    }

    def check_conditions(obj, where):
        if isinstance(obj, dict):
            c = obj.get("condition")
            if "op" in obj and isinstance(c, str) and c not in SRD_CONDITIONS and c not in ids:
                errors.append(f"{where}: состояние {c} нет ни в SRD, ни в пакете (свои — через id effect.*)")
            for v in obj.values():
                check_conditions(v, where)
        elif isinstance(obj, list):
            for v in obj:
                check_conditions(v, where)

    for path in sorted((ROOT / "data").rglob("*.yaml")):
        for rec in (load(path.read_text()) or {}).get("items") or []:
            if isinstance(rec, dict):
                check_conditions(rec, f"{path.relative_to(ROOT)}: {rec.get('id')}")

    for target, where in refs:
        if target not in ids:
            errors.append(f"{where}: ссылка на несуществующий id {target}")

    customs = []

    def find_custom(obj, where):
        if isinstance(obj, dict):
            if obj.get("op") == "custom":
                customs.append(where)
            for v in obj.values():
                find_custom(v, where)
        elif isinstance(obj, list):
            for v in obj:
                find_custom(v, where)

    for path in sorted((ROOT / "data").rglob("*.yaml")):
        doc = load(path.read_text()) or {}
        for rec in doc.get("items") or []:
            if isinstance(rec, dict):
                find_custom(rec, f"{path.relative_to(ROOT)}: {rec.get('id')}")

    for k, n in sorted(counts.items()):
        print(f"{k:20} {n}")
    print(f"итого записей: {sum(counts.values())}")
    print(f"не формализовано (op: custom, в игру не идёт): {len(customs)}")
    if "--customs" in sys.argv:
        print("\n".join(customs))
    if "--strict" in sys.argv and customs:
        errors.append(f"--strict: {len(customs)} записей op: custom")
    if errors:
        print(f"\nОШИБКИ ({len(errors)}):")
        print("\n".join(errors[:200]))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
