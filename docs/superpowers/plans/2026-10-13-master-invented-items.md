# Предметы, придуманные мастером: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда шаблона предмета нет в каталоге, мастер вне боя придумывает его с настоящей, ограниченной по силе
механикой; каждый случай пишется в журнал для ревью после сессии. Заодно сервер перестаёт исполнять заклинания,
которых игрок не заявлял.

**Architecture:** Промах каталога (`CatalogError` с `kind`/`rid`) в `execute` превращается в ошибку
`missing_content` и запоминается в `ToolContext.content_misses`. Новый инструмент `invent_item` проверяет запись
валидатором пакетов и потолком силы и кладёт её в пакет кампании `campaign.<id>` — новой неизменяемой версией,
которая встаёт последней в `campaign.content_chain`. Каталог видит записи-предложения своего пакета кампании.
Журнал — скрытое `Event`, строка `CONTENT_GAP` в логе и CLI-выгрузка YAML.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async (SQLite в тестах, PostgreSQL в проде), pydantic v2,
jsonschema, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-10-13-master-invented-items-design.md`

## Global Constraints

- Создаются только `item_template`; существа, эффекты, заклинания, умения, правила боя — нет.
- Только вне боя: `combat.in_combat(ctx)` ложно; в кампании-модуле (`adventure.is_module(ctx.campaign)`) — отказ.
- Для игрока придуманный предмет — обычный предмет; пометка видна только в журнале.
- Новых таблиц нет: пакет кампании живёт в `content_packs`/`content_records`.
- Разрешённые операции: `resource` (`stat: hp`, `delta` > 0, среднее ≤ 7, максимум ≤ 10), `add`
  (`target: temp_hp`, `value` 1–5), `remove_condition` (`poisoned`/`frightened`). Модификаторы — только у
  `category: consumable`. `op: custom`, `if`, `triggers` запрещены.
- Лимиты: 2 придуманных предмета за ход, 10 за кампанию; `give_item` придуманного предмета — не больше 10 штук.
- Цена не выше 50 зм (`price.cp` ≤ 5000).
- `invent_item` без промаха того же `missing_id` в этом ходу отклоняется (`code="no_content_gap"`).
- Код ошибки ставит сервер: `missing_content` из `CatalogError`, не из текста.
- Строка лога начинается с `CONTENT_GAP` (логирование процесса не настроено, префикса уровня нет).
- Тексты для модели и игрока — по-русски, в стиле соседнего кода.
- Не трогать незакоммиченную работу владельца: `item.goodberry` в `content/dnd5e-srd/data/gear.yaml`,
  `failed_item_action` в `app/agents/master/outcomes.py`, правки `app/tools/spells.py`, `app/tools/master/items.py`.
  Коммитить только свои файлы (`git add <путь>`), никогда `git add -A`.

## Review Focus

1. **Бесконечное лечение через не-расходник.** Мастер создаёт `category: trinket` с `resource hp` — предмет
   не расходуется и лечит каждый ход. Ожидание: отказ. Тест — Task 4, `test_modifiers_only_on_consumables`.
2. **Сотня ягод.** `give_item` придуманного предмета с `qty: 100`. Ожидание: отказ выше 10. Тест — Task 4,
   `test_give_invented_item_qty_capped`.
3. **Пакет кампании ломает выбор мира для звука.** `audio.pack_of` берёт последний пакет цепочки, а им станет
   `campaign.<id>`. Ожидание: мир — пакет сеттинга, а не пакет кампании. Тест — Task 2,
   `test_pack_of_skips_campaign_overlay`.
4. **Откат хода оставляет призрак.** `invent_item` прошёл, потом ход откатился; кэш каталога по ключу версии
   отдал бы старую запись при повторном номере версии. Ожидание: версия уникальна (суффикс случайный), после
   отката цепочка прежняя и шаблона нет. Тест — Task 2, `test_rollback_restores_chain`.
5. **Чужая кампания видит придуманное.** Ожидание: нет, и без `allow_proposals` своя кампания видит. Тест —
   Task 2, `test_overlay_is_visible_only_to_its_campaign`.

---

### Task 1: Сервер не исполняет заклинание, которого игрок не заявлял

**Files:**
- Modify: `app/agents/master/common.py` (новая функция `declared_cast` в конце файла)
- Modify: `app/agents/master/turn.py:562-569` (проверка в начале `run_call`, после проверки JSON)
- Test: `tests/test_undeclared_cast.py`

**Interfaces:**
- Produces: `declared_cast(messages: list, char_by_seat: dict, caster_id: str, spell_name: str) -> bool`

- [x] **Step 1: Write the failing tests**

```python
# ruff: noqa: F811 — shared integration fixtures
"""Вне боя мастер не творит заклинание, которого игрок в этом ходу не заявлял (кампания c_d45c8e2b5c660e33)."""

from app.agents.master.common import declared_cast
from app.db.models import Event, MasterTurn, Message
from tests.game import party
from tests.test_master import DONE, act, admin_g, game_client, llm, rows  # noqa: F401


def _msg(seat, content, intent=None, kind="action"):
    return Message(id="m", campaign_id="c", seq=1, seat_id=seat, kind=kind, content=content, intent=intent)


class _Ch:
    def __init__(self, cid):
        self.id = cid


def test_declared_by_parsed_verb_or_spell_name():
    seats = {"s1": _Ch("ch_1")}
    cast = {"actions": [{"verb": "cast", "spell_id": "spell.goodberry"}]}
    assert declared_cast([_msg("s1", "колдую", cast)], seats, "ch_1", "Добрая ягода")
    assert declared_cast([_msg("s1", "Творю «Добрая ягода» на себя")], seats, "ch_1", "Добрая ягода")
    search = {"actions": [{"verb": "search", "target_id": "en_1"}]}
    assert not declared_cast([_msg("s1", "Обыскиваю: Ящик экспедиции", search)], seats, "ch_1", "Добрая ягода")
    assert not declared_cast([_msg("s2", "Творю «Добрая ягода»")], seats, "ch_1", "Добрая ягода")


def test_model_cannot_cast_undeclared_spell(game_client, admin_g, llm, settings):
    c, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("cast_spell", {"caster_id": hero["id"], "spell_id": "spell.goodberry"})]},
        DONE,
        DONE,
        {"text": "Ты осматриваешься."},
    ]
    act(game_client, player, c["id"], "Осматриваюсь по сторонам")
    (turn,) = rows(settings, MasterTurn)
    call = next(x for x in turn.trace["calls"] if x["tool"] == "cast_spell")
    assert not call["result"]["ok"] and "не заявлял" in call["result"]["error"]
    assert not [e for e in rows(settings, Event) if e.tool == "cast_spell"]


def test_declared_spell_passes_the_guard(game_client, admin_g, llm, settings):
    c, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("cast_spell", {"caster_id": hero["id"], "spell_id": "spell.goodberry"})]},
        DONE,
        DONE,
        {"text": "Готово."},
    ]
    act(game_client, player, c["id"], "Творю «Добрая ягода»")
    (turn,) = rows(settings, MasterTurn)
    call = next(x for x in turn.trace["calls"] if x["tool"] == "cast_spell")
    assert "не заявлял" not in (call["result"].get("error") or "")  # дальше решают правила заклинаний
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_undeclared_cast.py -q`
Expected: FAIL — `ImportError: cannot import name 'declared_cast'`.

- [x] **Step 3: Implement `declared_cast`** (в конец `app/agents/master/common.py`)

```python
def declared_cast(messages: list, char_by_seat: dict, caster_id: str, spell_name: str) -> bool:
    """Заявил ли игрок заклинание в новых репликах хода: разбор парсера с ``cast`` или название в тексте.
    Название — запасной путь, когда парсер не узнал заклинание в свободной фразе."""
    name = spell_name.strip().lower()
    for m in messages:
        ch = char_by_seat.get(m.seat_id)
        if ch is None or ch.id != caster_id:
            continue
        if any(a.get("verb") == "cast" for a in (m.intent or {}).get("actions") or []):
            return True
        if name and name in (m.content or "").lower():
            return True
    return False
```

- [x] **Step 4: Wire the guard into `run_call`** (`app/agents/master/turn.py`, сразу после
  `if not isinstance(args, dict) or "__invalid_json__" in args: ...`)

```python
            if name == "cast_spell" and not combat.in_combat(ctx) and args.get("caster_id") in ctx.world.characters:
                spell = ctx.world.catalog.find(str(args.get("spell_id") or ""), "spell_template")
                if not declared_cast(new, char_by_seat, args["caster_id"], spell.name if spell else ""):
                    done_calls += 1
                    return {
                        "ok": False,
                        "error": "игрок этого заклинания в этом ходу не заявлял: не твори его за героя",
                    }
```

И импорт рядом с остальными из `app.agents.master.common` в начале `turn.py`: добавить `declared_cast`.

- [x] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_undeclared_cast.py tests/test_spells.py tests/test_shillelagh.py tests/test_master.py -q -n 4`
Expected: PASS. Если упал старый тест, где модель творит заклинание без заявки вне боя, — это и есть закрываемое
поведение: поправить текст заявки в тесте так, чтобы заклинание было названо, и указать это в отчёте.

- [x] **Step 6: Commit**

```bash
git add app/agents/master/common.py app/agents/master/turn.py tests/test_undeclared_cast.py
git commit -m "Мастер не творит заклинание, которого игрок не заявлял"
```

---

### Task 2: Пакет кампании для придуманных записей

**Files:**
- Create: `app/content/overlay.py`
- Modify: `app/content/catalog.py:84-85` (`CatalogView._ok`)
- Modify: `app/core/audio.py:508-513` (`pack_of`)
- Test: `tests/test_content_overlay.py`

**Interfaces:**
- Produces:
  - `OVERLAY_PREFIX = "campaign."`
  - `overlay_id(campaign_id: str) -> str`
  - `is_overlay(pack_id: str) -> bool`
  - `async overlay_records(session, campaign) -> list[ContentRecord]`
  - `async add_record(session, campaign, kind: str, record: dict) -> CatalogView` — новая версия пакета
    кампании со всеми прежними записями и этой; обновляет `campaign.content_chain`; возвращает свежий каталог.

- [x] **Step 1: Write the failing tests**

```python
"""Пакет кампании: записи, придуманные мастером, видит только своя кампания (спецификация 2026-10-13, §5)."""

from app.content import overlay
from app.content.catalog import campaign_catalog
from app.core import audio
from app.db.models import Campaign
from tests.game import import_base, party, run

BERRY = {
    "id": "item.goodberry",
    "name": "Добрая ягода",
    "status": "proposal",
    "category": "consumable",
    "price": {"cp": 0},
    "description": "Лечит 1 хит.",
    "modifiers": [{"op": "resource", "stat": "hp", "delta": 1}],
}


def _camp(client, admin, settings):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    return c["id"]


def test_overlay_is_visible_only_to_its_campaign(client, admin, settings):
    a = _camp(client, admin, settings)
    b, _h, _x = party(client, admin, names=["Боромир"])

    async def go(s):
        ca = await s.get(Campaign, a)
        view = await overlay.add_record(s, ca, "item_template", BERRY)
        await s.commit()
        assert not ca.settings.get("allow_proposals")
        assert view.find("item.goodberry", "item_template").data["modifiers"][0]["delta"] == 1
        assert ca.content_chain[-1][0] == overlay.overlay_id(a)
        other = await campaign_catalog(s, await s.get(Campaign, b["id"]))
        return other.find("item.goodberry", "item_template")

    assert run(settings, go) is None


def test_second_record_keeps_first_and_versions_are_unique(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        await overlay.add_record(s, c, "item_template", BERRY)
        v1 = c.content_chain[-1][1]
        view = await overlay.add_record(s, c, "item_template", {**BERRY, "id": "item.moss_salve", "name": "Мазь"})
        await s.commit()
        return v1, c.content_chain[-1][1], view, len(await overlay.overlay_records(s, c))

    v1, v2, view, n = run(settings, go)
    assert v1 != v2 and n == 2
    assert view.find("item.goodberry", "item_template") and view.find("item.moss_salve", "item_template")


def test_rollback_restores_chain(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        before = [list(x) for x in c.content_chain]
        nested = await s.begin_nested()
        await overlay.add_record(s, c, "item_template", BERRY)
        await nested.rollback()
        await s.refresh(c)
        view = await campaign_catalog(s, c)
        return before, c.content_chain, view.find("item.goodberry", "item_template")

    before, after, found = run(settings, go)
    assert before == after and found is None


def test_pack_of_skips_campaign_overlay(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        world = audio.pack_of(c)
        c.pack_id = None
        await overlay.add_record(s, c, "item_template", BERRY)
        return world, audio.pack_of(c)

    world, after = run(settings, go)
    assert after is not None and not overlay.is_overlay(after)
    assert world is None or after == world or not overlay.is_overlay(after)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_overlay.py -q`
Expected: FAIL — `ImportError: cannot import name 'overlay'`.

- [x] **Step 3: Implement `app/content/overlay.py`**

```python
"""Пакет кампании: записи, которые мастер придумал в игре (спецификация 2026-10-13, §5).

Пакет неизменен в своей версии, а каталог кешируется по цепочке версий. Поэтому каждое добавление — новая
версия со всеми прежними записями; суффикс версии случаен, чтобы откат хода и повтор не попали в чужой кэш.
Пакет кампании стоит последним в цепочке и перекрывает одноимённые записи мира.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlalchemy import select

from app.content.catalog import CatalogView, campaign_catalog
from app.db.models import Campaign, ContentPack, ContentRecord

OVERLAY_PREFIX = "campaign."
OVERLAY_KIND = "campaign_overlay"


def overlay_id(campaign_id: str) -> str:
    return f"{OVERLAY_PREFIX}{campaign_id}"[:64]


def is_overlay(pack_id: str | None) -> bool:
    return bool(pack_id) and str(pack_id).startswith(OVERLAY_PREFIX)


def _current(campaign: Campaign) -> str | None:
    pid = overlay_id(campaign.id)
    return next((v for p, v in campaign.content_chain or [] if p == pid), None)


async def overlay_records(session, campaign: Campaign) -> list[ContentRecord]:
    version = _current(campaign)
    if version is None:
        return []
    q = select(ContentRecord).where(
        ContentRecord.pack_id == overlay_id(campaign.id), ContentRecord.pack_version == version
    )
    return list((await session.scalars(q)).all())


async def add_record(session, campaign: Campaign, kind: str, record: dict) -> CatalogView:
    pid = overlay_id(campaign.id)
    old = [r for r in await overlay_records(session, campaign) if r.id != record["id"]]
    version = f"{len(old) + 1}-{secrets.token_hex(4)}"
    body = json.dumps([[r.id, r.data] for r in old] + [[record["id"], record]], ensure_ascii=False, sort_keys=True)
    session.add(
        ContentPack(
            id=pid,
            version=version,
            name=f"Придумано мастером: {campaign.name}"[:255],
            manifest={"id": pid, "kind": OVERLAY_KIND, "campaign_id": campaign.id},
            checksum=hashlib.sha256(body.encode()).hexdigest(),
            import_report={},
        )
    )
    for r in old:
        session.add(
            ContentRecord(pack_id=pid, pack_version=version, id=r.id, kind=r.kind, status=r.status, name=r.name,
                          data=r.data)  # fmt: skip
        )
    session.add(
        ContentRecord(
            pack_id=pid, pack_version=version, id=record["id"], kind=kind, status="proposal",
            name=str(record["name"])[:255], data=record,
        )  # fmt: skip
    )
    campaign.content_chain = [list(x) for x in campaign.content_chain or [] if x[0] != pid] + [[pid, version]]
    await session.flush()
    return await campaign_catalog(session, campaign)
```

- [x] **Step 4: Let the campaign see its own proposals** (`app/content/catalog.py`, `CatalogView._ok`)

```python
    def _ok(self, e: Entry | None) -> bool:
        # пакет кампании в цепочке — всегда свой: придуманное мастером видно без тестового режима
        return e is not None and (self.allow_proposals or e.status == "canon" or e.pack_id.startswith("campaign."))
```

- [x] **Step 5: World pack ignores the overlay** (`app/core/audio.py`, `pack_of`)

```python
def pack_of(campaign) -> str | None:
    """Мир кампании: её пакет сеттинга или верхний пакет цепочки, кроме пакета кампании."""
    if campaign.pack_id:
        return campaign.pack_id
    chain = [x for x in campaign.content_chain or [] if not str(x[0]).startswith("campaign.")]
    return chain[-1][0] if chain else None
```

- [x] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_overlay.py tests/test_audio.py tests/test_content*.py -q -n 4`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add app/content/overlay.py app/content/catalog.py app/core/audio.py tests/test_content_overlay.py
git commit -m "Пакет кампании хранит записи, придуманные мастером"
```

---

### Task 3: Промах каталога — ошибка `missing_content` и строка `CONTENT_GAP`

**Files:**
- Modify: `app/content/catalog.py` (`CatalogError.__init__`, `CatalogView.get`)
- Modify: `app/tools/registry.py` (поле `ToolContext.content_misses`; ветка `except` в `execute`)
- Test: `tests/test_content_gap.py`

**Interfaces:**
- Produces:
  - `CatalogError(message, *, rid: str | None = None, kind: str | None = None)`; атрибуты `.rid`, `.kind`
  - `ToolContext.content_misses: set[tuple[str, str]]` — `(kind, rid)` промахов этого хода
  - failure `{"code": "missing_content", "category": "rule_denial"}` для промаха `item_template`

- [x] **Step 1: Write the failing tests**

```python
"""Промах каталога предметов: сервер называет его missing_content и пишет CONTENT_GAP (спецификация 2026-10-13)."""

import logging

from tests.test_tools import call, game, play  # noqa: F401


def test_missing_item_template_is_content_gap(game, caplog):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        with caplog.at_level(logging.WARNING):
            r = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                               "qty": 2, "reason": "ягоды"})  # fmt: skip
        return r, set(ctx.content_misses)

    r, misses = play(settings, cid, [], fn)
    assert not r["ok"] and r["failure"]["code"] == "missing_content"
    assert r["failure"]["category"] == "rule_denial"
    assert "invent_item" in r["error"]
    assert misses == {("item_template", "item.goodberry_x")}
    line = next(x.getMessage() for x in caplog.records if x.getMessage().startswith("CONTENT_GAP"))
    assert "missing=item.goodberry_x" in line and "tool=give_item" in line and f"campaign={cid}" in line


def test_other_catalog_errors_stay_unclassified(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        r = await call(ctx, "spawn_entity", {"creature_template_id": "creature.nope", "name": "Никто"})
        return r, set(ctx.content_misses)

    r, misses = play(settings, cid, [], fn)
    assert not r["ok"] and r["failure"]["code"] != "missing_content" and misses == set()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_gap.py -q`
Expected: FAIL — `AttributeError: 'ToolContext' object has no attribute 'content_misses'`.

- [x] **Step 3: `CatalogError` carries what was missing** (`app/content/catalog.py`)

```python
class CatalogError(LookupError):
    def __init__(self, message: str = "", *, rid: str | None = None, kind: str | None = None):
        super().__init__(message)
        self.rid = rid
        self.kind = kind
```

И в `CatalogView.get`:

```python
            raise CatalogError(f"нет записи {what}{rid}", rid=rid, kind=kind)
```

- [x] **Step 4: Track misses on the context** (`app/tools/registry.py`, в `ToolContext` рядом с `operation_refs`)

```python
    content_misses: set[tuple[str, str]] = field(default_factory=set)  # (вид, id) шаблонов, которых нет: invent_item
```

Поле не входит в `CHANNELS` снимка (`app/tools/resolution/context.py`), поэтому откат вызова его не стирает —
промах должен пережить откат, ради этого он и записывается.

- [x] **Step 5: Classify in `execute`** (`app/tools/registry.py`, ветка `except (ToolError, WorldError, RulesError, DiceError, CatalogError) as e:` — заменить финальный `return _failure(...)`)

```python
        if isinstance(e, CatalogError) and e.kind == "item_template" and e.rid:
            ctx.content_misses.add((e.kind, e.rid))
            log.warning("CONTENT_GAP campaign=%s turn=%s tool=%s missing=%s", ctx.campaign.id, ctx.turn_id, name, e.rid)
            return _failure(
                f"{e}. Вне боя можно создать этот предмет через invent_item (missing_id={e.rid}) и повторить вызов",
                "missing_content",
                "rule_denial",
                key,
                rolled_back=True,
            )
        return _failure(
            str(e),
            e.code if isinstance(e, ToolError) else "unclassified",
            e.category if isinstance(e, ToolError) else "unknown",
            key,
            rolled_back=True,
        )
```

`ToolContext.turn_id` — поле хода (`app/tools/registry.py:65`), в тестах это `"t_test"`.

- [x] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_gap.py tests/test_tools.py tests/test_narration_integrity.py tests/test_resolution*.py -q -n 4`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add app/content/catalog.py app/tools/registry.py tests/test_content_gap.py
git commit -m "Промах шаблона предмета становится пробелом контента в журнале"
```

---

### Task 4: Инструмент `invent_item` с потолком силы и лимитами

**Files:**
- Create: `app/tools/master/invented.py`
- Modify: `app/tools/master/__init__.py` (импорт после `items`)
- Modify: `app/tools/master/items.py` (`give_item`: лимит 10 для придуманного)
- Test: `tests/test_invent_item.py`

**Interfaces:**
- Consumes: `overlay.add_record`, `overlay.overlay_records`, `overlay.is_overlay` (Task 2);
  `ToolContext.content_misses` (Task 3)
- Produces:
  - константы `MAX_PER_TURN = 2`, `MAX_PER_CAMPAIGN = 10`, `MAX_GIVE_QTY = 10`, `MAX_PRICE_CP = 5000`,
    `HEAL_AVG = 7`, `HEAL_MAX = 10`, `TEMP_HP_MAX = 5`, `REMOVABLE = {"poisoned", "frightened"}`
  - `power_errors(category: str, modifiers: list[dict]) -> list[str]`
  - инструмент `invent_item` (`InventItemArgs`), результат `{"item_template_id", "name", "invented": True}`

- [x] **Step 1: Write the failing tests**

```python
"""Мастер придумывает недостающий предмет с ограниченной механикой (спецификация 2026-10-13, §3–§4)."""

import logging

import pytest

from app.db.models import Campaign, Event
from app.tools.master.invented import power_errors
from tests.game import run
from tests.test_tools import call, game, play  # noqa: F401

HEAL = [{"op": "resource", "stat": "hp", "delta": 2}]


def _invent(missing="item.goodberry_x", **kw):
    return {
        "missing_id": missing,
        "name": "Добрая ягода",
        "description": "Лечит 2 хита.",
        "category": "consumable",
        "modifiers": HEAL,
        "reason": "ягоды от заклинания",
        **kw,
    }


async def _miss(ctx, hero, rid="item.goodberry_x", qty=3):
    return await call(ctx, "give_item", {"character_id": hero, "item_template_id": rid, "qty": qty, "reason": "-"})


@pytest.mark.parametrize(
    "category, mods, text",
    [
        ("consumable", [{"op": "resource", "stat": "hp", "delta": "3d8"}], "лечение"),
        ("consumable", [{"op": "resource", "stat": "hp", "delta": -3}], "лечение"),
        ("consumable", [{"op": "add", "target": "temp_hp", "value": 9}], "временных"),
        ("consumable", [{"op": "remove_condition", "condition": "paralyzed"}], "снять"),
        ("consumable", [{"op": "extra_damage", "dice": "1d6"}], "операция"),
        ("consumable", [{"op": "custom", "draft": "x"}], "операция"),
        ("consumable", [{"op": "resource", "stat": "hp", "delta": 1, "if": {"x": 1}}], "условия"),
        ("trinket", HEAL, "consumable"),
    ],
)
def test_power_ceiling(category, mods, text):
    errors = power_errors(category, mods)
    assert errors and any(text in e for e in errors), errors


def test_power_ceiling_accepts_srd_like_items():
    assert power_errors("consumable", [{"op": "resource", "stat": "hp", "delta": "2d4+2"}]) == []
    assert power_errors("consumable", [{"op": "add", "target": "temp_hp", "value": 5}]) == []
    assert power_errors("consumable", [{"op": "remove_condition", "any_of": ["poisoned"]}]) == []
    assert power_errors("trinket", []) == []


def test_invent_after_miss_then_give_and_use_heals(game, caplog):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        a = ctx.world.actor(hero)
        a.hp.current = a.hp.maximum - 5
        a.save_hp()
        assert not (await _miss(ctx, hero))["ok"]
        with caplog.at_level(logging.WARNING):
            made = await call(ctx, "invent_item", _invent())
        given = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                              "qty": 3, "reason": "ягоды"})  # fmt: skip
        inv = next(i for i in ctx.world.inventory[hero] if i.item_template_id == "item.goodberry_x")
        used = await call(ctx, "use_item", {"character_id": hero, "inventory_id": inv.id})
        return made, given, used, ctx.world.actor(hero).hp.current, ctx.world.actor(hero).hp.maximum

    made, given, used, hp, hp_max = play(settings, cid, [], fn)
    assert made["ok"] and made["result"]["item_template_id"] == "item.goodberry_x", made
    assert given["ok"] and used["ok"], (given, used)
    assert hp == hp_max - 3
    line = next(x.getMessage() for x in caplog.records if "invented=" in x.getMessage())
    assert line.startswith("CONTENT_GAP") and "missing=item.goodberry_x" in line and "resource:hp:2" in line
    ev = next(e for e in run(settings, lambda s: _events(s, cid)) if e.tool == "invent_item")
    assert ev.hidden and ev.payload["record"]["modifiers"] == HEAL and ev.payload["missing_id"] == "item.goodberry_x"


async def _events(s, cid):
    from sqlalchemy import select

    return (await s.scalars(select(Event).where(Event.campaign_id == cid))).all()


def test_invent_without_miss_is_refused(game):  # noqa: F811
    settings, cid, hero = game
    r = play(settings, cid, [], lambda ctx: call(ctx, "invent_item", _invent()))
    assert not r["ok"] and r["failure"]["code"] == "no_content_gap"


def test_invent_refused_in_combat_and_modules(game):  # noqa: F811
    settings, cid, hero = game

    async def combat(ctx):
        await _miss(ctx, hero)
        ctx.world.scene.mode, ctx.world.scene.turn_order = "combat", [hero]
        return await call(ctx, "invent_item", _invent())

    assert "бою" in play(settings, cid, [], combat)["error"]

    async def module(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "module": "m_1"}
        await s.commit()

    run(settings, module)

    async def again(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent())

    assert "модул" in play(settings, cid, [], again)["error"]


def test_modifiers_only_on_consumables(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent(category="trinket"))

    r = play(settings, cid, [], fn)
    assert not r["ok"] and "consumable" in r["error"]


def test_per_turn_limit(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        out = []
        for i in range(3):
            rid = f"item.gap_{i}"
            await _miss(ctx, hero, rid)
            out.append(await call(ctx, "invent_item", _invent(missing=rid, name=f"Ягода {i}")))
        return out

    a, b, c = play(settings, cid, [], fn)
    assert a["ok"] and b["ok"] and not c["ok"] and "за ход" in c["error"]


def test_give_invented_item_qty_capped(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        await call(ctx, "invent_item", _invent())
        return await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                             "qty": 50, "reason": "-"})  # fmt: skip

    r = play(settings, cid, [], fn)
    assert not r["ok"] and "10" in r["error"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_invent_item.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tools.master.invented'`.

- [x] **Step 3: Implement `app/tools/master/invented.py`**

```python
"""Предмет, которого нет в каталоге, мастер придумывает сам (спецификация 2026-10-13).

Только вне боя и только чтобы закрыть промах каталога этого хода. Механика — на языке модификаторов пакета,
в пределах обычного предмета SRD и только из операций, которые ``use_item`` действительно исполняет.
Запись ложится в пакет кампании (app/content/overlay.py) и в журнал пробелов контента.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.content import overlay
from app.content.loader import _core_validators
from app.core import adventure, combat
from app.rules.dice import DiceError, parse
from app.tools.registry import ToolContext, ToolError, tool

log = logging.getLogger(__name__)

MAX_PER_TURN = 2
MAX_PER_CAMPAIGN = 10
MAX_GIVE_QTY = 10
MAX_PRICE_CP = 5000  # 50 зм: дороже обычного предмета SRD не бывает
HEAL_AVG = 7  # как зелье лечения 2к4+2
HEAL_MAX = 10
TEMP_HP_MAX = 5
REMOVABLE = {"poisoned", "frightened"}


def _heal_errors(delta) -> list[str]:
    if isinstance(delta, bool):
        return ["лечение: delta — число или кубики"]
    if isinstance(delta, int):
        avg = top = delta
    elif isinstance(delta, str):
        try:
            expr = parse(delta)
        except DiceError:
            return [f"лечение: формула {delta!r} не читается"]
        dice = [t for t in expr.terms if not t.is_constant]
        if any(t.sign < 0 for t in dice):
            return ["лечение: кубики со знаком минус не допускаются"]
        avg = sum(t.count * (t.sides + 1) / 2 for t in dice) + expr.modifier
        top = sum(t.count * t.sides for t in dice) + expr.modifier
    else:
        return ["лечение: delta — число или кубики"]
    if avg <= 0:
        return ["лечение: только восстановление хитов, урон предмет не наносит"]
    if avg > HEAL_AVG or top > HEAL_MAX:
        return [f"лечение: в среднем не больше {HEAL_AVG} и не больше {HEAL_MAX} хитов, как зелье лечения 2к4+2"]
    return []


def power_errors(category: str, modifiers: list[dict]) -> list[str]:
    """Нарушения потолка силы; пустой список — запись допустима."""
    errors: list[str] = []
    if modifiers and category != "consumable":
        errors.append("механика бывает только у расходника (category: consumable): иначе предмет не тратится")
    for m in modifiers:
        op = m.get("op")
        if "if" in m or "triggers" in m:
            errors.append(f"{op}: условия и триггеры придуманному предмету недоступны")
        elif op == "resource" and m.get("stat") in ("hp", "stat.hp"):
            errors += _heal_errors(m.get("delta"))
        elif op == "add" and m.get("target") == "temp_hp":
            v = m.get("value")
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= TEMP_HP_MAX:
                errors.append(f"временных хитов — от 1 до {TEMP_HP_MAX}")
        elif op == "remove_condition":
            names = m.get("any_of") or [m.get("condition")]
            bad = [n for n in names if str(n or "").removeprefix("condition.") not in REMOVABLE]
            if bad or not names:
                errors.append(f"снять можно только {', '.join(sorted(REMOVABLE))}")
        else:
            errors.append(
                f"операция {op!r} недоступна: можно resource hp, add temp_hp, remove_condition"
            )
    return errors


class InventItemArgs(BaseModel):
    missing_id: str = Field(pattern=r"^item\.[a-z0-9_]+$", description="id из ошибки missing_content этого хода")
    name: str = Field(min_length=1, max_length=80, description="название для игроков")
    description: str = Field(min_length=1, max_length=400, description="что это и что делает, видно игроку")
    category: Literal["consumable", "gear", "trinket"]
    modifiers: list[dict] = Field(default_factory=list, max_length=3, description="механика на языке пакета")
    weight: float = Field(0, ge=0, le=20)
    price_cp: int = Field(0, ge=0, le=MAX_PRICE_CP)
    reason: str = Field(min_length=1, max_length=300, description="зачем: «ягоды от заклинания Добрая ягода»")


def _ops_text(modifiers: list[dict]) -> str:
    parts = []
    for m in modifiers:
        bits = [str(m.get("op"))] + [str(m[k]) for k in ("stat", "target", "condition") if m.get(k)]
        bits += [str(m[k]) for k in ("delta", "value") if m.get(k) is not None]
        parts.append(":".join(bits))
    return ",".join(parts) or "-"


@tool(
    "invent_item",
    "Создаёт предмет, которого нет в каталоге, после ошибки missing_content в этом ходу. Только вне боя. "
    "Механика: resource hp (до 2к4+2), add temp_hp (до 5), remove_condition poisoned/frightened; "
    "механика только у consumable. Потом повтори исходный вызов с missing_id.",
    InventItemArgs,
    closes=False,
)
async def invent_item(ctx: ToolContext, a: InventItemArgs) -> dict:
    if combat.in_combat(ctx):
        raise ToolError("в бою недостающее не придумывается: откажи или реши иначе", code="invent_in_combat",
                        category="rule_denial")  # fmt: skip
    if adventure.is_module(ctx.campaign):
        raise ToolError("в готовом модуле канон книги: недостающий предмет не придумывается", code="invent_in_module",
                        category="rule_denial")  # fmt: skip
    if ("item_template", a.missing_id) not in ctx.content_misses:
        raise ToolError(f"в этом ходу не было промаха {a.missing_id}: придумывать можно только недостающее",
                        code="no_content_gap", category="rule_denial")  # fmt: skip
    made = [e for e in ctx.events if e.tool == "invent_item"]
    if len(made) >= MAX_PER_TURN:
        raise ToolError(f"не больше {MAX_PER_TURN} придуманных предметов за ход", code="invent_limit",
                        category="rule_denial")  # fmt: skip
    if len(await overlay.overlay_records(ctx.session, ctx.campaign)) >= MAX_PER_CAMPAIGN:
        raise ToolError(f"в кампании уже {MAX_PER_CAMPAIGN} придуманных предметов: дождись ревью владельца",
                        code="invent_limit", category="rule_denial")  # fmt: skip
    errors = power_errors(a.category, a.modifiers)
    record = {
        "id": a.missing_id,
        "name": a.name,
        "status": "proposal",
        "description": a.description,
        "category": a.category,
        "price": {"cp": a.price_cp},
        "weight": a.weight,
        "tags": ["invented"],
        "modifiers": a.modifiers,
    }
    validator = _core_validators().get("item_template")
    if validator is not None:
        errors += [f"{'/'.join(map(str, e.path)) or 'запись'}: {e.message}" for e in validator.iter_errors(record)]
    if errors:
        raise ToolError("; ".join(errors[:4]), code="invent_rejected", category="invalid_arguments")
    view = await overlay.add_record(ctx.session, ctx.campaign, "item_template", record)
    await ctx.record(
        "invent_item",
        payload={"missing_id": a.missing_id, "record": record, "reason": a.reason},
        hidden=True,
    )
    ctx.world.catalog = view
    log.warning(
        'CONTENT_GAP campaign=%s turn=%s missing=%s invented="%s" ops=%s',
        ctx.campaign.id, ctx.turn_id, a.missing_id, a.name, _ops_text(a.modifiers),
    )  # fmt: skip
    return {"item_template_id": a.missing_id, "name": a.name, "invented": True}
```

`ctx.events` содержит `Event` текущего хода (`ToolContext.events`); `e.tool` — имя инструмента события.
`ctx.world.catalog` присваивается последним: если что-то упадёт раньше, `execute` перечитает мир со старым
каталогом.

- [x] **Step 4: Register the tool** (`app/tools/master/__init__.py`, сразу после строки с `items`)

```python
from app.tools.master import invented  # noqa: F401
```

- [x] **Step 5: Cap quantity of invented items** (`app/tools/master/items.py`, `give_item`, сразу после
  `rec = ctx.world.catalog.get(a.item_template_id, "item_template")`)

```python
    if rec.pack_id.startswith("campaign.") and a.qty > 10:
        raise ToolError("придуманный мастером предмет выдаётся не больше 10 штук за раз")
```

В этом файле есть незакоммиченные правки владельца: добавить только эти две строки и закоммитить файл
через `git add -p app/tools/master/items.py`, выбрав лишь свой фрагмент.

- [x] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_invent_item.py tests/test_content_overlay.py tests/test_content_gap.py tests/test_tools.py tests/test_playtest_items.py -q -n 4`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add app/tools/master/invented.py app/tools/master/__init__.py tests/test_invent_item.py
git add -p app/tools/master/items.py
git commit -m "Мастер придумывает недостающий предмет с ограниченной механикой"
```

---

### Task 5: Мастер проходит путь целиком в живом ходе

**Files:**
- Modify: `app/agents/prompts/` — системный промпт фазы решения: файл, где перечислены правила инструментов
  предметов (найти: `grep -rln "give_item" app/agents/prompts`). Добавить одну строку.
- Test: `tests/test_invent_item.py` (добавить тест сквозного хода)

**Interfaces:**
- Consumes: `invent_item` (Task 4), `missing_content` (Task 3)

- [x] **Step 1: Write the failing end-to-end test** (в конец `tests/test_invent_item.py`)

```python
from app.db.models import InventoryItem, MasterTurn  # noqa: E402
from tests.game import party  # noqa: E402
from tests.test_master import DONE, act, admin_g, game_client, llm, rows  # noqa: E402, F401


def test_master_turn_invents_and_gives(game_client, admin_g, llm, settings):  # noqa: F811
    c, (player,), hero = party(game_client, admin_g)
    give = {"character_id": hero["id"], "item_template_id": "item.mossberry", "qty": 3, "reason": "собранные ягоды"}
    llm.replies += [
        {"tool_calls": [("give_item", give)]},
        {"tool_calls": [("invent_item", {**_invent(missing="item.mossberry"), "name": "Моховая ягода"})]},
        {"tool_calls": [("give_item", give)]},
        DONE,
        DONE,
        {"text": "Ты собираешь три моховые ягоды."},
    ]
    act(game_client, player, c["id"], "Собираю ягоды с мха у входа")
    items = [i for i in rows(settings, InventoryItem) if i.item_template_id == "item.mossberry"]
    assert items and items[0].qty == 3
    (turn,) = rows(settings, MasterTurn)
    codes = [(x["tool"], (x["result"].get("failure") or {}).get("code")) for x in turn.trace["calls"]]
    assert ("give_item", "missing_content") in codes and ("invent_item", None) in codes
```

- [x] **Step 2: Run test to verify it fails or passes**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_invent_item.py::test_master_turn_invents_and_gives -q`
Expected: если FAIL — разобрать причину по `turn.trace` (лимит вызовов, `allowed`, `item_fallback` из работы
владельца). `invent_item` не входит в `HOST_TOOLS` и не `internal`, поэтому `decision_tools` должен его
отдавать. Если `failed_item_action` владельца заменяет прозу на сводку из-за первого неудачного `give_item` —
это ожидаемо: он смотрит последнюю попытку по ключу, а повторный `give_item` с тем же ключом успешен.

- [x] **Step 3: Teach the master** (промпт фазы решения, рядом с правилами про предметы)

```text
- Если инструмент ответил missing_content (шаблона предмета нет), вне боя создай предмет через invent_item
  с тем же missing_id и честной скромной механикой, затем повтори исходный вызов. Не описывай в рассказе
  предмет, которого нет в инвентаре.
```

- [x] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_invent_item.py tests/test_master.py tests/test_narration_integrity.py tests/test_prompts*.py -q -n 4`
Expected: PASS. Если есть тест-снимок промпта — обновить снимок.

- [x] **Step 5: Commit**

```bash
git add tests/test_invent_item.py app/agents/prompts/<изменённый файл>
git commit -m "Мастер создаёт недостающий предмет в живом ходе и повторяет выдачу"
```

---

### Task 6: Выгрузка пробелов для ревью и документация

**Files:**
- Create: `tools/content_gaps.py`
- Modify: `docs/master-resolution.md` (новый раздел «Пробелы контента»)
- Test: `tests/test_content_gaps_tool.py`

**Interfaces:**
- Consumes: `Event(tool="invent_item")` (Task 4), `overlay.overlay_records` (Task 2)
- Produces: `async collect(session, campaign_id: str | None) -> list[dict]` — элементы
  `{"campaign_id", "missing_id", "record", "reason", "created_at"}`; `to_yaml(items: list[dict]) -> str`

- [x] **Step 1: Write the failing test**

```python
"""Выгрузка придуманных мастером предметов для ревью после сессии."""

import yaml

from app.content.loader import _core_validators
from tests.game import run
from tests.test_invent_item import _invent, _miss
from tests.test_tools import call, game, play  # noqa: F401
from tools.content_gaps import collect, to_yaml


def test_export_is_valid_pack_yaml(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent())

    assert play(settings, cid, [], fn)["ok"]
    items = run(settings, lambda s: collect(s, cid))
    assert [i["missing_id"] for i in items] == ["item.goodberry_x"]
    doc = yaml.safe_load(to_yaml(items))
    assert doc["kind"] == "item_template"
    rec = doc["items"][0]
    assert rec["status"] == "proposal" and rec["id"] == "item.goodberry_x"
    assert list(_core_validators().get("item_template").iter_errors(rec)) == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_gaps_tool.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.content_gaps'` (пакет `tools` импортируется
из тестов так же, как в `tests/test_narrative_quality.py`: `from tools.eval_narrative import ...`).

- [x] **Step 3: Implement `tools/content_gaps.py`**

```python
"""Пробелы контента: предметы, которые мастер придумал в игре, — готовым YAML для пакета.

    uv run python tools/content_gaps.py c_d45c8e2b5c660e33
    uv run python tools/content_gaps.py --all

Перенос в пакет — решение владельца: поменять status на canon, поправить механику или выбросить запись.
"""

from __future__ import annotations

import argparse
import asyncio

import yaml
from sqlalchemy import select

from app.db.models import Event


async def collect(session, campaign_id: str | None) -> list[dict]:
    q = select(Event).where(Event.tool == "invent_item")
    if campaign_id:
        q = q.where(Event.campaign_id == campaign_id)
    rows = (await session.scalars(q.order_by(Event.created_at))).all()
    return [
        {
            "campaign_id": e.campaign_id,
            "missing_id": e.payload["missing_id"],
            "record": e.payload["record"],
            "reason": e.payload.get("reason", ""),
            "created_at": e.created_at.isoformat() if e.created_at else "",
        }
        for e in rows
    ]


def to_yaml(items: list[dict]) -> str:
    latest = {i["missing_id"]: i["record"] for i in items}  # последняя версия записи на id
    return yaml.safe_dump({"kind": "item_template", "items": list(latest.values())}, allow_unicode=True,
                          sort_keys=False)  # fmt: skip


async def _main(campaign_id: str | None) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import Settings

    engine = create_async_engine(Settings.from_env().database_url)
    async with async_sessionmaker(engine)() as s:
        items = await collect(s, campaign_id)
    for i in items:
        print(f"# {i['created_at']} {i['campaign_id']} {i['missing_id']}: {i['reason']}")
    print(to_yaml(items))
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("campaign_id", nargs="?")
    p.add_argument("--all", action="store_true")
    a = p.parse_args()
    asyncio.run(_main(None if a.all else a.campaign_id))
```

`Settings.from_env()` читает окружение и `.env` так же, как сервер (`app/main.py:77`).

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -o addopts='' -p no:cacheprovider tests/test_content_gaps_tool.py -q`
Expected: PASS.

- [x] **Step 5: Document** (`docs/master-resolution.md`, перед разделом «Диагностика»)

```markdown
## Пробелы контента

Если шаблона предмета нет в каталоге, `execute` возвращает `missing_content` и пишет строку
`CONTENT_GAP campaign=… turn=… tool=… missing=…`. Вне боя и вне модуля мастер может закрыть этот промах
инструментом `invent_item`: запись проходит валидатор пакетов и потолок силы обычного предмета SRD
(`app/tools/master/invented.py`) и ложится в пакет кампании `campaign.<id>` (`app/content/overlay.py`) со
статусом `proposal`. Придумать можно только то, на что этот ход уже наткнулся. Каждое создание — скрытое
событие `invent_item` и строка `CONTENT_GAP … invented=…`. После сессии `tools/content_gaps.py` выдаёт
YAML для переноса в пакет; решение о каноне принимает владелец.
```

- [x] **Step 6: Full verification**

Run:
```bash
.venv/Scripts/python.exe -m ruff check app tools tests
.venv/Scripts/python.exe -m ruff format --check app tools tests
.venv/Scripts/python.exe -m app.contract --check
LITELLM_LOCAL_MODEL_COST_MAP=True .venv/Scripts/python.exe -m pytest -o addopts='' -n 8 -p no:cacheprovider -q -rs
```
Expected: всё зелёное; пропуски — только тесты, которым нужен PostgreSQL.

- [x] **Step 7: Commit**

```bash
git add tools/content_gaps.py tests/test_content_gaps_tool.py docs/master-resolution.md docs/superpowers/specs/2026-10-13-master-invented-items-design.md docs/superpowers/plans/2026-10-13-master-invented-items.md
git commit -m "Выгрузка придуманных мастером предметов для ревью"
```
