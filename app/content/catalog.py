"""Записи пакетов кампании во время игры: цепочка из БД, исключения, переопределения и наследование по srd_ref.

Пакет неизменен в своей версии, поэтому каталог цепочки кешируется в памяти процесса. В игровой кампании
видны только записи ``canon``; ``proposal`` — только если в настройках кампании включён тестовый режим.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.importer import latest_version
from app.db.models import Campaign, ContentPack, ContentRecord

BASE_RULES = "srd-5.1"
BASE_PACK_ID = "dnd5e-srd"


class CatalogError(LookupError):
    pass


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    status: str
    pack_id: str
    data: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data.get("name", self.id))


class Catalog:
    def __init__(self, entries: dict[str, Entry], base_entries: list[Entry] = ()):
        self._all = entries
        # srd_ref (тип, имя) → запись базового пакета: запись мира наследует от неё числа. Индекс строится
        # до переопределений: класс мира с тем же id, что у SRD, берёт таблицу уровней из записи SRD.
        self._srd: dict[tuple[str, str], Entry] = {}
        for e in base_entries:
            ref = e.data.get("srd_ref")
            if isinstance(ref, dict):
                self._srd.setdefault((ref.get("type"), ref.get("name")), e)
        self._resolved: dict[str, Entry] = {}

    def view(self, allow_proposals: bool) -> CatalogView:
        return CatalogView(self, allow_proposals)

    def raw(self, rid: str) -> Entry | None:
        return self._all.get(rid)

    def resolve(self, rid: str) -> Entry | None:
        """Запись с полями базовой записи SRD под своими: мир меняет имя и описание, числа берутся из SRD."""
        if rid in self._resolved:
            return self._resolved[rid]
        e = self._all.get(rid)
        if e is None:
            return None
        ref = e.data.get("srd_ref")
        base = self._srd.get((ref.get("type"), ref.get("name"))) if isinstance(ref, dict) else None
        if base is not None and base is not e and base.kind == e.kind:
            data = {**base.data, **{k: v for k, v in e.data.items() if v not in (None, [], "srd")}}
            if e.data.get("levels") == "srd":
                data["levels"] = base.data.get("levels", [])
            e = Entry(e.id, e.kind, e.status, e.pack_id, data)
        self._resolved[rid] = e
        return e

    def entries(self) -> list[Entry]:
        return list(self._all.values())


class CatalogView:
    """Каталог, каким его видит кампания: без черновиков, если это не тестовая кампания."""

    def __init__(self, catalog: Catalog, allow_proposals: bool):
        self.catalog = catalog
        self.allow_proposals = allow_proposals

    def _ok(self, e: Entry | None) -> bool:
        return e is not None and (self.allow_proposals or e.status == "canon")

    def get(self, rid: str, kind: str | None = None) -> Entry:
        e = self.catalog.resolve(rid)
        if not self._ok(e) or (kind is not None and e.kind != kind):
            what = f"{kind} " if kind else ""
            raise CatalogError(f"нет записи {what}{rid}")
        return e

    def find(self, rid: str, kind: str | None = None) -> Entry | None:
        try:
            return self.get(rid, kind)
        except CatalogError:
            return None

    def by_kind(self, kind: str) -> list[Entry]:
        out = []
        for e in self.catalog.entries():
            if e.kind == kind and self._ok(e):
                out.append(self.catalog.resolve(e.id))
        return sorted(out, key=lambda e: e.id)

    def search(self, kind: str, query: str = "", limit: int = 10) -> list[Entry]:
        """Поиск шаблона по словам в id, имени, тегах и описании. Семантический поиск — этап «Память»."""
        words = [w for w in query.lower().split() if w]
        scored = []
        for e in self.by_kind(kind):
            hay = " ".join(
                [e.id, e.name, " ".join(map(str, e.data.get("tags") or [])), str(e.data.get("description", ""))]
            ).lower()
            ref = e.data.get("srd_ref")
            if isinstance(ref, dict):
                hay += " " + str(ref.get("name", "")).lower()
            score = sum(1 for w in words if w in hay)
            if score or not words:
                scored.append((-score, e.id, e))
        return [e for _, _, e in sorted(scored)[:limit]]

    def dc_scale(self) -> list[Entry]:
        return sorted(self.by_kind("dc_scale"), key=lambda e: (int(e.data["value"]), e.id))

    def condition(self, name: str) -> Entry:
        return self.get(name if "." in name else f"condition.{name}", "effect_template")


_cache: dict[tuple[tuple[str, str], ...], Catalog] = {}


async def resolve_chain(session: AsyncSession, pack: ContentPack | None) -> list[list[str]]:
    """Цепочка для новой кампании: последний базовый пакет правил, на который опирается пакет мира, и сам пакет."""
    base = await latest_version(session, BASE_PACK_ID)
    if pack is None:
        if base is None:
            raise CatalogError("базовый пакет правил не импортирован: python -m app.content import content/dnd5e-srd")
        return [[base.id, base.version]]
    chain: list[list[str]] = []
    rb = pack.manifest.get("ruleset_base")
    if rb and not pack.manifest.get("provides"):
        providers = (await session.scalars(select(ContentPack))).all()
        candidates = [p for p in providers if p.manifest.get("provides") == rb]
        if not candidates:
            raise CatalogError(f"не импортирован базовый пакет {rb}")
        from app.content.manifest import version_tuple

        b = max(candidates, key=lambda p: version_tuple(p.version))
        chain.append([b.id, b.version])
    for dep in pack.manifest.get("depends") or []:
        dep_id = dep.get("id") if isinstance(dep, dict) else str(dep)
        d = await latest_version(session, dep_id)
        if d is not None and [d.id, d.version] not in chain:
            chain.append([d.id, d.version])
    chain.append([pack.id, pack.version])
    return chain


async def load_catalog(session: AsyncSession, chain: list[list[str]]) -> Catalog:
    key = tuple((p, v) for p, v in chain)
    if key in _cache:
        return _cache[key]
    entries: dict[str, Entry] = {}
    base_entries: list[Entry] = []
    for pack_id, version in key:
        pack = await session.get(ContentPack, (pack_id, version))
        if pack is None:
            raise CatalogError(f"пакет {pack_id} {version} не импортирован")
        is_base = pack.manifest.get("provides") == BASE_RULES or pack_id == BASE_PACK_ID
        for rid in pack.manifest.get("excludes") or []:
            entries.pop(rid, None)
        rows = await session.scalars(
            select(ContentRecord).where(ContentRecord.pack_id == pack_id, ContentRecord.pack_version == version)
        )
        for r in rows:
            e = Entry(r.id, r.kind, r.status, pack_id, r.data)
            entries[r.id] = e
            if is_base:
                base_entries.append(e)
    cat = Catalog(entries, base_entries)
    _cache[key] = cat
    return cat


def from_packs(chain) -> Catalog:
    """Каталог цепочки, загруженной с диска (app/content/loader.py), — для проверок до записи пакета в БД."""
    entries: dict[str, Entry] = {}
    base_entries: list[Entry] = []
    for pack in chain:
        is_base = pack.manifest.provides == BASE_RULES or pack.id == BASE_PACK_ID
        for rid in pack.manifest.excludes:
            entries.pop(rid, None)
        for r in pack.records.values():
            e = Entry(r.id, r.kind, r.status, pack.id, r.data)
            entries[r.id] = e
            if is_base:
                base_entries.append(e)
    return Catalog(entries, base_entries)


async def campaign_catalog(session: AsyncSession, campaign: Campaign) -> CatalogView:
    chain = campaign.content_chain
    if not chain:
        chain = campaign.content_chain = await resolve_chain(session, None)
    cat = await load_catalog(session, chain)
    return cat.view(bool((campaign.settings or {}).get("allow_proposals")))


def clear_cache() -> None:
    _cache.clear()
