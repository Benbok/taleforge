"""Загрузка и проверка пакетов контента (ТЗ, раздел 3.2, шаги импорта 1–4).

Шаги: схема (ядро + схема пакета) → ссылки (внутри пакета и его зависимостей) → совместимость
с движком → отчёт. Запись в БД (шаг 5) и нарезка базы знаний (шаг 6) — на этапе каркаса.
Одна и та же проверка работает локально из командной строки и на сервере при импорте.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

from app.content.manifest import PackManifest, version_satisfies, version_tuple
from app.content.vocab import CUSTOM_OP, ENGINE_VERSION, MODIFIER_OPS, TRIGGER_EVENTS
from app.content.yaml_io import load_file

CORE_SCHEMA_PATH = Path(__file__).parent / "schema" / "core.yaml"


class PackError(Exception):
    """Пакет нельзя загрузить: нет паспорта или он неверен, не найдена зависимость."""


@dataclass(frozen=True)
class Record:
    id: str
    kind: str
    data: dict[str, Any]
    file: str
    pack_id: str

    @property
    def status(self) -> str:
        return self.data.get("status", "proposal")


@dataclass
class Pack:
    manifest: PackManifest
    root: Path
    records: dict[str, Record] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version


@dataclass
class Report:
    pack_id: str
    version: str
    counts: dict[str, int] = field(default_factory=dict)
    customs: list[str] = field(default_factory=list)
    proposals: int = 0
    overrides: list[str] = field(default_factory=list)
    unknown_events: dict[str, int] = field(default_factory=dict)
    unresolved_srd_refs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"Пакет {self.pack_id} {self.version}"]
        lines += [f"  {k:20} {n}" for k, n in sorted(self.counts.items())]
        lines.append(f"  итого записей: {self.total}")
        lines.append(f"  в статусе proposal: {self.proposals}")
        lines.append(f"  не формализовано (op: custom, в игру не идёт): {len(self.customs)}")
        if self.overrides:
            lines.append(f"  переопределяет записи зависимостей: {len(self.overrides)}")
        if self.unresolved_srd_refs:
            lines.append(f"  srd_ref без записи в базовом пакете: {len(self.unresolved_srd_refs)}")
        if self.unknown_events:
            ev = ", ".join(f"{k} ({n})" for k, n in sorted(self.unknown_events.items()))
            lines.append(f"  события триггеров вне словаря ядра: {ev}")
        return "\n".join(lines)


# --- Схемы ---


@cache
def _core_schema() -> dict[str, Any]:
    return load_file(CORE_SCHEMA_PATH)


def _kind_schema(schema: dict[str, Any], kind: str) -> dict[str, Any] | None:
    k = (schema.get("kinds") or {}).get(kind)
    if k is None:
        return None
    return {
        "allOf": [schema.get("common") or {}, {"type": "object", **k}],
        "definitions": schema.get("definitions") or {},
    }


class _Validators:
    def __init__(self, schema: dict[str, Any]):
        self.schema = schema
        self._cache: dict[str, jsonschema.Draft7Validator | None] = {}

    def kinds(self) -> set[str]:
        return set((self.schema.get("kinds") or {}).keys())

    def get(self, kind: str) -> jsonschema.Draft7Validator | None:
        if kind not in self._cache:
            s = _kind_schema(self.schema, kind)
            self._cache[kind] = jsonschema.Draft7Validator(s) if s is not None else None
        return self._cache[kind]


@cache
def _core_validators() -> _Validators:
    return _Validators(_core_schema())


# --- Обход записи ---


def _walk_ops(obj: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Все объекты с ``op``. Внутрь ``op: custom`` не заходим: его черновик (draft) — заявка, не механика."""
    if isinstance(obj, dict):
        if "op" in obj:
            yield path, obj
            if obj.get("op") == CUSTOM_OP:
                return
        for k, v in obj.items():
            yield from _walk_ops(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_ops(v, f"{path}/{i}")


def _walk_trigger_events(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        if obj.get("op") == CUSTOM_OP:
            return
        for k, v in obj.items():
            if k == "triggers" and isinstance(v, list):
                for t in v:
                    if isinstance(t, dict) and isinstance(t.get("on"), str):
                        yield t["on"]
            yield from _walk_trigger_events(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_trigger_events(v)


def _walk_refs(obj: Any) -> Iterator[str]:
    """Ссылки на записи: поля ``*_ref`` (строка) и ``*_refs`` (список строк). Внутрь custom не заходим."""
    if isinstance(obj, dict):
        if obj.get("op") == CUSTOM_OP:
            return
        for k, v in obj.items():
            if isinstance(k, str) and k.endswith("_ref") and isinstance(v, str):
                yield v
            elif isinstance(k, str) and k.endswith("_refs") and isinstance(v, list):
                yield from (x for x in v if isinstance(x, str))
            else:
                yield from _walk_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_refs(v)


_CONDITION_OPS = {"condition", "remove_condition", "immunity", "resistance", "vulnerability"}


def _condition_names(obj: Any) -> Iterator[str]:
    """Имена состояний в ``op: condition`` / ``remove_condition`` и в защитах от состояний."""
    for _, op in _walk_ops(obj):
        if op.get("op") not in _CONDITION_OPS:
            continue
        c = op.get("condition")
        if isinstance(c, str):
            yield c
        any_of = op.get("any_of")
        if op.get("op") == "remove_condition" and isinstance(any_of, list):
            yield from (x for x in any_of if isinstance(x, str))


def _walk_srd_refs(obj: Any) -> Iterator[tuple[str, str]]:
    if isinstance(obj, dict):
        s = obj.get("srd_ref")
        if isinstance(s, dict) and "type" in s and "name" in s:
            yield str(s["type"]), str(s["name"])
        for k, v in obj.items():
            if k != "srd_ref":
                yield from _walk_srd_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_srd_refs(v)


# --- Загрузка ---


def read_manifest(root: Path) -> PackManifest:
    path = root / "pack.yaml"
    if not path.is_file():
        raise PackError(f"{root}: нет pack.yaml")
    try:
        return PackManifest.model_validate(load_file(path))
    except ValidationError as e:
        raise PackError(f"{path}: паспорт пакета неверен:\n{e}") from None


def load_pack(root: Path | str, deps: Sequence[Pack] = (), strict: bool = False) -> tuple[Pack, Report]:
    """Загружает пакет и проверяет его против ядра, своей схемы и зависимостей.

    Ошибки данных не бросаются исключением, а собираются в отчёт: так автор видит все сразу.
    ``strict`` — записи с ``op: custom`` тоже ошибка.
    """
    root = Path(root)
    manifest = read_manifest(root)
    pack = Pack(manifest, root)
    report = Report(manifest.id, manifest.version)

    _check_engine(manifest, report)
    _check_dependencies(manifest, deps, report)

    core = _core_validators()
    own_schema_path = root / "schema" / "schema.yaml"
    own = _Validators(load_file(own_schema_path)) if own_schema_path.is_file() else None

    data_dir = root / "data"
    if not data_dir.is_dir():
        report.errors.append(f"{root}: нет папки data/")
        return pack, report

    counts: Counter[str] = Counter()
    events: Counter[str] = Counter()
    for path in sorted(data_dir.rglob("*.yaml")):
        rel = str(path.relative_to(root))
        try:
            doc = load_file(path)
        except Exception as e:  # noqa: BLE001 — ошибка разбора YAML любого вида идёт в отчёт
            report.errors.append(f"{rel}: YAML: {e}")
            continue
        if not isinstance(doc, dict) or "kind" not in doc or "items" not in doc:
            report.errors.append(f"{rel}: файл должен быть вида {{kind, items}}")
            continue
        kind = doc["kind"]
        validator = core.get(kind)
        if validator is None:
            report.errors.append(f"{rel}: неизвестный вид записей {kind!r} (нет в ядровой схеме)")
            continue
        own_validator = own.get(kind) if own is not None and kind in own.kinds() else None

        for i, rec in enumerate(doc["items"] or []):
            if not isinstance(rec, dict):
                report.errors.append(f"{rel}: запись #{i} не объект")
                continue
            rid = str(rec.get("id", f"#{i}"))
            where = f"{rel}: {rid}"
            for v in (validator, own_validator):
                if v is None:
                    continue
                for err in v.iter_errors(rec):
                    loc = "/".join(map(str, err.path))
                    report.errors.append(f"{where}: {loc + ' ' if loc else ''}{err.message}")
            if rid in pack.records:
                report.errors.append(f"{where}: дубликат id (уже в {pack.records[rid].file})")
                continue
            pack.records[rid] = Record(rid, kind, rec, rel, manifest.id)
            counts[kind] += 1
            if rec.get("status") == "proposal":
                report.proposals += 1

            for opath, op in _walk_ops(rec):
                name = op.get("op")
                if name == CUSTOM_OP:
                    report.customs.append(f"{where}{opath}")
                elif name not in MODIFIER_OPS:
                    report.errors.append(f"{where}{opath}: движок не умеет op {name!r}")
            events.update(e for e in _walk_trigger_events(rec) if e not in TRIGGER_EVENTS)

    report.counts = dict(counts)
    report.unknown_events = dict(events)
    if report.unknown_events:
        report.warnings.append(
            "события триггеров вне словаря ядра: такие триггеры не сработают, пока движок их не поддержит"
        )

    _check_refs(pack, deps, report)
    if strict and report.customs:
        report.errors.append(f"--strict: {len(report.customs)} мест с op: custom")
    return pack, report


def _check_engine(manifest: PackManifest, report: Report) -> None:
    req = manifest.engine
    if req is None:
        return
    if version_tuple(req.min_version) > version_tuple(ENGINE_VERSION):
        report.errors.append(f"пакету нужен движок {req.min_version}, есть {ENGINE_VERSION}")
    missing = sorted(set(req.ops) - MODIFIER_OPS)
    if missing:
        report.errors.append(f"пакету нужны op, которых нет в движке: {', '.join(missing)}")
    missing_ev = sorted(set(req.triggers) - TRIGGER_EVENTS)
    if missing_ev:
        report.errors.append(f"пакету нужны события триггеров, которых нет в движке: {', '.join(missing_ev)}")


def _check_dependencies(manifest: PackManifest, deps: Sequence[Pack], report: Report) -> None:
    by_id = {d.id: d for d in deps}
    for dep_id, constraint in manifest.depends.items():
        d = by_id.get(dep_id)
        if d is None:
            report.errors.append(f"не найдена зависимость {dep_id} {constraint}")
        elif not version_satisfies(d.version, constraint):
            report.errors.append(f"зависимость {dep_id}: нужна {constraint}, есть {d.version}")
    if manifest.ruleset_base and not any(d.manifest.provides == manifest.ruleset_base for d in deps):
        report.warnings.append(
            f"базовый пакет правил {manifest.ruleset_base} не подключён: ссылки srd_ref не проверены"
        )


def _check_refs(pack: Pack, deps: Sequence[Pack], report: Report) -> None:
    excluded = set(pack.manifest.excludes)
    visible: dict[str, Record] = {}
    for d in deps:
        visible.update(d.records)
    for rid in sorted(excluded):
        if rid not in visible:
            report.warnings.append(f"excludes: в зависимостях нет записи {rid}")
    for rid in excluded:
        visible.pop(rid, None)
    report.overrides = sorted(rid for rid in pack.records if rid in visible)
    visible.update(pack.records)

    for rec in pack.records.values():
        for target in _walk_refs(rec.data):
            if target in excluded:
                report.errors.append(f"{rec.file}: {rec.id}: ссылка на исключённую запись {target}")
            elif target not in visible:
                report.errors.append(f"{rec.file}: {rec.id}: ссылка на несуществующий id {target}")

    if any(rid.startswith("condition.") for rid in visible):
        for rec in pack.records.values():
            for name in _condition_names(rec.data):
                # Имя состояния SRD (poisoned → condition.poisoned) или id эффекта пакета (effect.bleeding).
                target = name if "." in name else f"condition.{name}"
                if target not in visible:
                    report.errors.append(f"{rec.file}: {rec.id}: нет состояния {name!r} (нужна запись {target})")

    base = [d for d in deps if d.manifest.provides and d.manifest.provides == pack.manifest.ruleset_base]
    if pack.manifest.provides or not base:
        return
    srd_index = {pair for d in base for r in d.records.values() for pair in _walk_srd_refs(r.data)}
    missing = Counter(
        f"{t}: {n}" for rec in pack.records.values() for t, n in _walk_srd_refs(rec.data) if (t, n) not in srd_index
    )
    report.unresolved_srd_refs = sorted(missing)


# --- Поиск зависимостей и реестр ---


def discover_packs(packs_root: Path | str) -> dict[str, Path]:
    """Все пакеты в папке: id → путь. Пакетом считается подпапка с pack.yaml."""
    out: dict[str, Path] = {}
    for p in sorted(Path(packs_root).glob("*/pack.yaml")):
        out[read_manifest(p.parent).id] = p.parent
    return out


def load_with_dependencies(
    root: Path | str, packs_root: Path | str | None = None, strict: bool = False
) -> tuple[list[Pack], Report]:
    """Загружает пакет вместе с базовым пакетом правил и зависимостями из ``packs_root``.

    Возвращает цепочку пакетов от базы к верхнему и отчёт по верхнему пакету."""
    root = Path(root)
    manifest = read_manifest(root)
    available: dict[str, Path] = {}
    if packs_root is not None:
        available = {k: v for k, v in discover_packs(packs_root).items() if v.resolve() != root.resolve()}

    chain: list[Pack] = []
    seen: set[str] = set()

    def need(pid: str) -> None:
        if pid in seen or pid not in available:
            return
        seen.add(pid)
        m = read_manifest(available[pid])
        for dep in _required(m, available):
            need(dep)
        pack, rep = load_pack(available[pid], chain)
        if not rep.ok:
            raise PackError(f"зависимость {pid} не проходит проверку:\n" + "\n".join(rep.errors[:20]))
        chain.append(pack)

    for dep in _required(manifest, available):
        need(dep)
    pack, report = load_pack(root, chain, strict=strict)
    return [*chain, pack], report


def _required(m: PackManifest, available: dict[str, Path]) -> Iterable[str]:
    ids = list(m.depends)
    if m.ruleset_base and not m.provides:
        for pid, path in available.items():
            if read_manifest(path).provides == m.ruleset_base and pid not in ids:
                ids.insert(0, pid)
    return ids


class ContentRegistry:
    """Записи цепочки пакетов с учётом исключений и переопределений: верхний пакет главнее."""

    def __init__(self, packs: Sequence[Pack]):
        self.packs = list(packs)
        records: dict[str, Record] = {}
        for p in self.packs:
            for rid in p.manifest.excludes:
                records.pop(rid, None)
            records.update(p.records)
        self._records = records

    def get(self, rid: str) -> Record:
        try:
            return self._records[rid]
        except KeyError:
            raise KeyError(f"нет записи {rid}") from None

    def __contains__(self, rid: str) -> bool:
        return rid in self._records

    def by_kind(self, kind: str, canon_only: bool = False) -> list[Record]:
        return [r for r in self._records.values() if r.kind == kind and (not canon_only or r.status == "canon")]

    def dc_scale(self) -> list[Record]:
        """Шкала сложностей: мастер выбирает сложность только отсюда, если её нет у объекта или NPC."""
        return sorted(self.by_kind("dc_scale"), key=lambda r: (r.data["value"], r.id))

    def dc(self, rid: str) -> int:
        rec = self.get(rid)
        if rec.kind != "dc_scale":
            raise KeyError(f"{rid} не запись шкалы сложностей")
        return int(rec.data["value"])

    def condition(self, name: str) -> Record:
        """Состояние SRD по имени из ``op: condition`` (``poisoned`` → ``condition.poisoned``)."""
        return self.get(f"condition.{name}")
