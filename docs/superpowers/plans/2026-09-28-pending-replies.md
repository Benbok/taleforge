# Ожидающая реплика: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При ИИ-мастере у игрока может быть только одна реплика, ждущая хода; её можно отменить, пока ход не начался, и все видят её статус.

**Architecture:** «Ожидающая» вычисляется из существующих данных: `seq` реплики больше `max(MasterTurn.upto_seq)`. Новые функции в `app/core/chat.py` отвечают на вопросы «есть ли ожидающая», «какой статус у реплик» и «можно ли отменить». Проверка отправки (`combat.gate_message`) и список действий (`actions.available`) используют их. WebSocket получает `message.withdraw`, а мастер рассылает `message.state` в начале и в конце хода. React-клиент в `web/` показывает статус и кнопку «Отменить», причину блокировки берёт из `blocked`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest (SQLite в тестах); React 19 + TypeScript + Zustand, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-pending-replies-design.md`

## Global Constraints

- Правило действует только при ИИ-мастере (`master_seat(c).occupant_type == "agent"`) и идущей сессии.
- Виды реплик под правилом: `action`, `speech`, `whisper`. `ooc` проходит всегда.
- Текст отказа, дословно: `Ваша реплика ждёт мастера. Отмените её, чтобы написать другую, или пишите вне игры через //.`
- Отказы отмены, дословно: `Мастер уже отвечает на эту реплику.` и `Эту реплику отменить нельзя.`
- Значения `state`: `pending` | `processing` | `answered` | `failed` | `null`.
- Статус хода без реплик после отмены: `skipped`.
- Механика мастера (окно сбора, фазы, промпты, парсер) не меняется.
- Прежний клиент `app/web/static/index.html` не трогаем.
- Тексты интерфейса и комментарии — по-русски, как в остальном коде.

## Review Focus

- Две реплики, отправленные почти одновременно, могут обе пройти проверку: это допустимо, так же уже работает боевой `submitted`. Тест не нужен, но менять поведение нельзя.
- Отмена чужой реплики или реплики другой кампании по подставленному `message_id` должна давать отказ `Эту реплику отменить нельзя.` — тест в задаче 2.
- Ход сражения (`advance`) пишет `MasterTurn` с тем же `upto_seq`, что у предыдущего хода; статус реплики берётся от первого по времени хода с этим `upto_seq`, иначе `answered` может смениться на `processing` — тест в задаче 1.
- После паузы сессии ожидающие реплики не должны показываться «ждёт мастера» (ход без сессии не начнётся) — `state` = `null`, тест в задаче 1.
- Отменённая реплика не должна вернуться при досылке после переподключения: она удалена из БД, снимок её не содержит — тест в задаче 2.

---

### Task 1: Ожидающая реплика на сервере: проверка, список действий, статус

**Files:**
- Modify: `app/core/chat.py`
- Modify: `app/gateway/events.py`
- Modify: `app/core/combat.py` (функция `gate_message`, строки ~353-374)
- Modify: `app/core/actions.py`
- Modify: `app/gateway/ws.py` (`_snapshot`, `_send`)
- Test: `tests/test_pending.py` (новый)

**Interfaces:**
- Produces (`app/core/chat.py`):
  - `PENDING_KINDS: tuple[str, ...] = ("action", "speech", "whisper")`
  - `PENDING_REASON: str`
  - `async def claimed_upto(session, campaign_id: str) -> int`
  - `async def pending_message(session, campaign: Campaign, seat_id: str | None) -> Message | None`
  - `async def message_states(session, campaign: Campaign, msgs: list[Message]) -> dict[str, str]`
  - `message_payload(msg, names=None, state: str | None = None)` — добавляет ключ `"state"`
- Produces (`app/gateway/events.py`): `publish_message(bus, msg, names=None, state: str | None = None)`
- Produces (`app/core/actions.py`): `available(...)` возвращает ещё ключ `"pending": {"id": str, "created_at": str} | None`
- Produces (снимок): ключ `"collect_window_sec": int`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_pending.py`:

```python
"""Ожидающая реплика при ИИ-мастере: одна на игрока, отмена и статус (docs/superpowers/specs/2026-09-28-pending-replies-design.md)."""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.db.models import MasterTurn, Message
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, ok, party, run
from tests.test_ws import connect, next_of

REASON = "Ваша реплика ждёт мастера. Отмените её, чтобы написать другую, или пишите вне игры через //."


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def client(settings, llm):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        c.app.state.master.notify = lambda cid: None  # мастер сам ход не начинает: реплика остаётся ожидающей
        yield c


@pytest.fixture
def admin(client):
    root = login(client, "root", "rootpass")
    ok(client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
    return login(client, "Arty", "secret1")


def say(ws, text, kind="auto"):
    ws.send_json({"type": "message.send", "payload": {"kind": kind, "text": text}})
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] in ("message.new", "message.rejected"):
            return e
    raise AssertionError("нет ответа на реплику")


def add_turn(settings, cid, upto, status):
    async def go(s):
        s.add(MasterTurn(campaign_id=cid, upto_seq=upto, status=status, trace={"from_seq": upto}))
        await s.commit()

    run(settings, go)


def test_second_reply_rejected_while_first_waits(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        first = say(ws, "Лезу на стену")
        assert first["type"] == "message.new" and first["payload"]["state"] == "pending"
        second = say(ws, "А нет, прыгаю на уступ")
        assert second["type"] == "message.rejected" and second["payload"]["reason"] == REASON
        whisper = say(ws, "мастер, тут есть ловушки?", kind="whisper")
        assert whisper["type"] == "message.rejected"
        ooc = say(ws, "// пойду за чаем")
        assert ooc["type"] == "message.new" and ooc["payload"]["kind"] == "ooc" and ooc["payload"]["state"] is None


def test_next_reply_allowed_once_turn_took_it(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        first = say(ws, "Лезу на стену")
        add_turn(settings, c["id"], first["payload"]["seq"], "running")
        nxt = say(ws, "Оглядываюсь с вершины")
        assert nxt["type"] == "message.new" and nxt["payload"]["state"] == "pending"


def test_no_limit_with_human_master(client, admin):
    c, (p1,), _ = party(client, admin, master={"type": "owner"})
    with connect(client, p1, c["id"]) as (ws, _):
        assert say(ws, "Лезу на стену")["payload"]["state"] is None
        assert say(ws, "Прыгаю на уступ")["type"] == "message.new"


def test_actions_block_play_and_offer_withdraw(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, snap):
        assert "chat.play" in snap["payload"]["actions"] and snap["payload"]["pending"] is None
        assert snap["payload"]["collect_window_sec"] == 0  # party() создаёт кампанию с окном 0
        m = say(ws, "Лезу на стену")["payload"]
        ws.send_json({"type": "actions.get", "payload": {}})
        st = next_of(ws, "state.actions")["payload"]
        assert "chat.play" not in st["actions"] and "chat.whisper" not in st["actions"]
        assert st["blocked"]["chat.play"] == REASON and st["blocked"]["chat.whisper"] == REASON
        assert "chat.withdraw" in st["actions"] and "chat.ooc" in st["actions"]
        assert st["pending"]["id"] == m["id"]


def test_states_in_snapshot(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        a = say(ws, "Лезу на стену")["payload"]
    add_turn(settings, c["id"], a["seq"], "done")
    # ход боя (advance) пишет тот же upto_seq позже: статус берётся от первого хода
    add_turn(settings, c["id"], a["seq"], "running")
    with connect(client, p1, c["id"]) as (ws, _):
        b = say(ws, "Спускаюсь")["payload"]
    add_turn(settings, c["id"], b["seq"], "failed")
    with connect(client, p1, c["id"]) as (ws, _):
        d = say(ws, "Иду к воротам")["payload"]
    with connect(client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
    assert states[a["id"]] == "answered" and states[b["id"]] == "failed" and states[d["id"]] == "pending"
    sys = [m for m in snap["payload"]["messages"] if m["kind"] == "system"]
    assert all(m["state"] is None for m in sys)


def test_no_pending_state_when_session_paused(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        a = say(ws, "Лезу на стену")["payload"]
    ok(client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin))
    with connect(client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
        assert states[a["id"]] is None and snap["payload"]["pending"] is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py -q`
Expected: FAIL — `KeyError: 'state'` / `KeyError: 'pending'`.

- [ ] **Step 3: Функции в `app/core/chat.py`**

Импорты: к `from sqlalchemy import select, update` добавить `func`; к моделям — `MasterTurn`:

```python
from sqlalchemy import func, select, update

...
from app.db.models import Campaign, GameSession, MasterTurn, Message, now
```

После `OOC_PREFIX = "//"`:

```python
PENDING_KINDS = ("action", "speech", "whisper")  # реплики, на которые отвечает ИИ-мастер
PENDING_REASON = "Ваша реплика ждёт мастера. Отмените её, чтобы написать другую, или пишите вне игры через //."
TURN_STATES = {"running": "processing", "done": "answered", "failed": "failed"}
```

`message_payload` — новый параметр и ключ:

```python
def message_payload(msg: Message, names: dict[str, str] | None = None, state: str | None = None) -> dict[str, Any]:
    return {
        ...  # прежние ключи без изменений
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "state": state,  # статус реплики игрока при ИИ-мастере: pending | processing | answered | failed
    }
```

В конец модуля:

```python
async def claimed_upto(session: AsyncSession, campaign_id: str) -> int:
    """До какого seq реплики игроков уже взяты ходами мастера."""
    q = select(func.max(MasterTurn.upto_seq)).where(MasterTurn.campaign_id == campaign_id)
    return await session.scalar(q) or 0


async def _ai_live(session: AsyncSession, campaign: Campaign) -> bool:
    return master_seat(campaign).occupant_type == "agent" and await active_session(session, campaign.id) is not None


async def pending_message(session: AsyncSession, campaign: Campaign, seat_id: str | None) -> Message | None:
    """Реплика места, которую ещё не взял ни один ход ИИ-мастера. Только при ИИ-мастере и идущей сессии."""
    if seat_id is None or not await _ai_live(session, campaign):
        return None
    q = (
        select(Message)
        .where(
            Message.campaign_id == campaign.id,
            Message.seat_id == seat_id,
            Message.kind.in_(PENDING_KINDS),
            Message.seq > await claimed_upto(session, campaign.id),
        )
        .order_by(Message.seq)
    )
    return (await session.scalars(q)).first()


async def message_states(session: AsyncSession, campaign: Campaign, msgs: list[Message]) -> dict[str, str]:
    """Статус реплик игроков при ИИ-мастере. Ход реплики — первый ход с наименьшим upto_seq >= seq: ходы идут
    по очереди, а ход боя (advance) повторяет upto_seq предыдущего и реплик не берёт."""
    if master_seat(campaign).occupant_type != "agent":
        return {}
    players = {s.id for s in campaign.seats if s.role == "player"}
    mine = [m for m in msgs if m.kind in PENDING_KINDS and m.seat_id in players]
    if not mine:
        return {}
    q = (
        select(MasterTurn.upto_seq, MasterTurn.status)
        .where(MasterTurn.campaign_id == campaign.id, MasterTurn.upto_seq >= min(m.seq for m in mine))
        .order_by(MasterTurn.upto_seq, MasterTurn.started_at)
    )
    turns: list[tuple[int, str]] = []
    for upto, status in (await session.execute(q)).all():
        if not turns or turns[-1][0] != upto:
            turns.append((upto, status))
    live = await active_session(session, campaign.id) is not None
    out: dict[str, str] = {}
    for m in mine:
        t = next((t for t in turns if t[0] >= m.seq), None)
        if t is None:
            if live:
                out[m.id] = "pending"
        else:
            out[m.id] = TURN_STATES.get(t[1], "answered")
    return out
```

- [ ] **Step 4: `publish_message` с состоянием (`app/gateway/events.py`)**

```python
async def publish_message(bus, msg: Message, names: dict[str, str] | None = None, state: str | None = None) -> None:
    await bus.publish(
        msg.campaign_id,
        envelope("message.new", msg.campaign_id, message_payload(msg, names, state), msg.seq),
        msg.visible_to,
    )
```

- [ ] **Step 5: Проверка отправки (`app/core/combat.py`, `gate_message`)**

Заменить начало функции (до `from app.core.world import get_scene` включительно) на:

```python
async def gate_message(session, viewer, kind: str, *, mark: bool = True) -> str | None:
    """В бою пишет только игрок, чей ход (раздел 5). Вне игры (//) — всегда можно.
    Действие занимает ход: второе действие до ответа мастера не принимается. При ИИ-мастере у игрока одна
    ожидающая реплика (действие, речь или шёпот) — и в бою, и вне боя. Возвращает причину отказа."""
    from app.core.chat import PENDING_KINDS, PENDING_REASON, pending_message
    from app.core.world import get_scene

    if not viewer.is_player:
        return None
    if kind in PENDING_KINDS and await pending_message(session, viewer.campaign, viewer.seat.id) is not None:
        return PENDING_REASON
    if kind not in ("action", "speech"):
        return None
```

Остальная часть функции (`sc = await get_scene(...)` и дальше) не меняется.

- [ ] **Step 6: Список действий (`app/core/actions.py`)**

Импорт: `from app.core.chat import PENDING_REASON, active_session, pending_message`.

В начале `available` завести `pending: dict[str, str] | None = None` и все `return` вернуть как
`{"actions": actions, "blocked": blocked, "pending": pending}` (их пять). Ветку игрока, начиная с
`actions.append("chat.whisper")`, заменить на:

```python
    msg = await pending_message(session, c, seat.id)
    if msg is not None:
        pending = {"id": msg.id, "created_at": msg.created_at.isoformat() if msg.created_at else None}
        blocked["chat.play"] = blocked["chat.whisper"] = PENDING_REASON
        actions.append("chat.withdraw")
        if in_combat:
            ch = await session.get(Character, current) if current else None
            if ch is not None and ch.seat_id == seat.id:
                actions.append("turn.pass")
        return {"actions": actions, "blocked": blocked, "pending": pending}

    actions.append("chat.whisper")
```

Остальное без изменений. Добавить в комментарий списка действий: `chat.withdraw — отменить ожидающую реплику`.

- [ ] **Step 7: Снимок и новая реплика (`app/gateway/ws.py`)**

В `_snapshot` после `msgs = await chat.history(...)`:

```python
    states = await chat.message_states(session, c, msgs)
```

В словаре снимка: `"messages": [chat.message_payload(m, names, states.get(m.id)) for m in msgs],` и новый ключ
`"collect_window_sec": int((c.settings or {}).get("collect_window_sec", 60)),`.

В `_send` внутри `async with maker() as session:` после `names = await _names(session, viewer.campaign)`:

```python
            state = (await chat.message_states(session, viewer.campaign, [m])).get(m.id)
```

и публикация: `await publish_message(bus, m, names, state)`.

- [ ] **Step 8: Прогнать тесты**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py tests/test_ws.py tests/test_master.py tests/test_combat.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/core/chat.py app/gateway/events.py app/core/combat.py app/core/actions.py app/gateway/ws.py tests/test_pending.py
git commit -m "Одна ожидающая реплика игрока при ИИ-мастере и её статус"
```

---

### Task 2: Отмена ожидающей реплики

**Files:**
- Modify: `app/core/chat.py`
- Modify: `app/core/combat.py`
- Modify: `app/gateway/ws.py` (новый обработчик и строка в docstring модуля)
- Test: `tests/test_pending.py`

**Interfaces:**
- Consumes: `chat.PENDING_KINDS`, `chat.claimed_upto`, `chat._ai_live` (задача 1).
- Produces:
  - `async def chat.withdraw_message(session, viewer: Viewer, message_id: str) -> Message` — удаляет, иначе `Conflict`.
  - `async def combat.unsubmit(session, viewer) -> None` — снимает `scene.state.submitted`, если ход этого игрока.
  - WS: входящее `message.withdraw {message_id}`; исходящее `message.withdrawn {id, seq}` (автору ещё `text`).

- [ ] **Step 1: Написать падающие тесты** (дописать в `tests/test_pending.py`)

```python
def withdraw(ws, mid):
    ws.send_json({"type": "message.withdraw", "payload": {"message_id": mid}})
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] in ("message.withdrawn", "message.rejected") and (
            "text" in e["payload"] or e["type"] == "message.rejected"
        ):
            return e
    raise AssertionError("нет ответа на отмену")


def test_withdraw_own_pending(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Лезу на стену")["payload"]
        e = withdraw(ws, m["id"])
        assert e["payload"] == {"id": m["id"], "seq": m["seq"], "text": "Лезу на стену"}
        assert say(ws, "Прыгаю на уступ")["type"] == "message.new"  # ограничение снято
    assert run(settings, lambda s: s.get(Message, m["id"])) is None
    with connect(client, p1, c["id"], last_seq=0) as (_, snap):  # досылка не возвращает отменённое
        assert m["id"] not in {x["id"] for x in snap["payload"]["messages"]}


def test_others_see_withdrawn(client, admin):
    c, (p1, p2), _ = party(client, admin, players=2)
    with connect(client, p2, c["id"]) as (ws2, _):
        with connect(client, p1, c["id"]) as (ws1, _):
            m = say(ws1, "Лезу на стену")["payload"]
            withdraw(ws1, m["id"])
        e = next_of(ws2, "message.withdrawn")
        assert e["payload"] == {"id": m["id"], "seq": m["seq"]}


def test_withdraw_refused_for_taken_and_foreign(client, admin, settings):
    c, (p1, p2), _ = party(client, admin, players=2)
    with connect(client, p1, c["id"]) as (ws1, _):
        m = say(ws1, "Лезу на стену")["payload"]
        with connect(client, p2, c["id"]) as (ws2, _):
            e = withdraw(ws2, m["id"])
            assert e["type"] == "message.rejected" and e["payload"]["reason"] == "Эту реплику отменить нельзя."
            assert withdraw(ws2, "m_nope")["payload"]["reason"] == "Эту реплику отменить нельзя."
        add_turn(settings, c["id"], m["seq"], "running")
        e = withdraw(ws1, m["id"])
        assert e["type"] == "message.rejected" and e["payload"]["reason"] == "Мастер уже отвечает на эту реплику."


def test_withdraw_in_combat_clears_submitted(client, admin, settings):
    from app.db.models import Scene

    c, (p1,), hero = party(client, admin)

    async def fight(s):
        sc = await s.get(Scene, c["id"])
        sc.mode, sc.turn_order, sc.state = "combat", [{"id": hero["id"], "initiative": 10}], {"turn": 0}
        await s.commit()

    run(settings, fight)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Бью мечом")["payload"]
        assert run(settings, lambda s: s.get(Scene, c["id"])).state["submitted"] is True
        withdraw(ws, m["id"])
    assert run(settings, lambda s: s.get(Scene, c["id"])).state["submitted"] is False
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py -q -k withdraw`
Expected: FAIL — `неизвестное событие 'message.withdraw'` (тест не дождётся ответа).

- [ ] **Step 3: `chat.withdraw_message`** (в конец `app/core/chat.py`)

```python
async def withdraw_message(session: AsyncSession, viewer: Viewer, message_id: str) -> Message:
    """Игрок отменяет свою реплику, пока её не взял ход ИИ-мастера. Реплика удаляется."""
    m = await session.get(Message, message_id)
    seat = viewer.seat
    if (
        m is None
        or m.campaign_id != viewer.campaign.id
        or seat is None
        or m.seat_id != seat.id
        or m.kind not in PENDING_KINDS
        or not await _ai_live(session, viewer.campaign)
    ):
        raise Conflict("Эту реплику отменить нельзя.")
    if m.seq <= await claimed_upto(session, viewer.campaign.id):
        raise Conflict("Мастер уже отвечает на эту реплику.")
    await session.delete(m)
    await session.flush()
    return m
```

- [ ] **Step 4: `combat.unsubmit`** (в `app/core/combat.py` после `gate_message`)

```python
async def unsubmit(session, viewer) -> None:
    """Отменённое действие освобождает ход: заявку можно сделать заново."""
    from app.core.world import get_scene

    sc = await get_scene(session, viewer.campaign.id)
    st = dict(sc.state or {})
    if sc.mode != "combat" or not sc.turn_order or not st.get("submitted") or viewer.seat is None:
        return
    ch = await session.get(Character, sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"])
    if ch is not None and ch.seat_id == viewer.seat.id:
        sc.state = {**st, "submitted": False}
```

- [ ] **Step 5: Обработчик в `app/gateway/ws.py`**

Новых импортов не нужно: всё нужное уже импортировано (`chat`, `combat`, `available`, `envelope`, `Conflict`, `NotFound`).
В цикле рядом с `message.send`:

```python
            if kind == "message.withdraw":
                await _withdraw(app, user, conn, payload)
                continue
```

Функция после `_send`:

```python
async def _withdraw(app, user: User, conn: Connection, payload: dict) -> None:
    """Игрок отменяет ожидающую реплику: она исчезает у всех, автору текст возвращается в поле ввода."""
    maker, bus = app.state.sessionmaker, app.state.bus
    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id)
            m = await chat.withdraw_message(session, viewer, str(payload.get("message_id") or ""))
            gone = {"id": m.id, "seq": m.seq}
            text, visible_to = m.content, m.visible_to
            if m.kind == "action":
                await combat.unsubmit(session, viewer)
            await session.commit()
            actions = await available(session, viewer)
        except (Conflict, NotFound) as e:
            await session.rollback()
            await conn.send(envelope("message.rejected", conn.campaign_id, {"reason": str(e)}))
            return
    await bus.publish(conn.campaign_id, envelope("message.withdrawn", conn.campaign_id, gone), visible_to)
    await conn.send(envelope("message.withdrawn", conn.campaign_id, {**gone, "text": text}))
    await conn.send(envelope("state.actions", conn.campaign_id, actions))
```

В docstring модуля добавить строку: ```` ``message.withdraw`` — отменить свою ожидающую реплику (``message.withdrawn`` всем, кто её видел). ````

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py tests/test_ws.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/chat.py app/core/combat.py app/gateway/ws.py tests/test_pending.py
git commit -m "Отмена ожидающей реплики"
```

---

### Task 3: Мастер рассылает статус реплик и пропускает пустой ход

**Files:**
- Modify: `app/agents/master.py` (`_run_turn` ~272-342, `_play` ~387-395)
- Test: `tests/test_pending.py`

**Interfaces:**
- Consumes: `MasterTurn.status` получает новое значение `"skipped"`.
- Produces: WS `message.state {ids: list[str], state: "processing" | "answered" | "failed"}` всем участникам.
  `_play` возвращает `{"ctx", "messages", "names", "ids", "skipped": bool}`.

- [ ] **Step 1: Написать падающие тесты** (дописать в `tests/test_pending.py`)

```python
DONE = {"text": "готово"}


def test_turn_publishes_states(settings, llm):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        root = login(c, "root", "rootpass")
        ok(c.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
        adm = login(c, "Arty", "secret1")
        camp, (p1,), _ = party(c, adm)
        llm.replies += [DONE, DONE, {"text": "Стена оказалась скользкой."}]
        with connect(c, p1, camp["id"]) as (ws, _):
            m = say(ws, "Лезу на стену")["payload"]
            states = []
            for _ in range(40):
                e = ws.receive_json()
                if e["type"] == "message.state":
                    states.append((e["payload"]["ids"], e["payload"]["state"]))
                if len(states) == 2:
                    break
            c.portal.call(c.app.state.master.wait_idle, camp["id"])
    assert states == [([m["id"]], "processing"), ([m["id"]], "answered")]


def test_empty_batch_is_skipped_without_model(client, admin, settings, llm):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Лезу на стену")["payload"]
        withdraw(ws, m["id"])

    async def turn(s):
        t = MasterTurn(campaign_id=c["id"], upto_seq=m["seq"], trace={"from_seq": m["seq"]})
        s.add(t)
        await s.commit()
        return t.id

    tid = run(settings, turn)

    async def play():
        async with client.app.state.sessionmaker() as s:
            return await client.app.state.master._play(s, c["id"], tid, [])

    out = client.portal.call(play)
    assert out["skipped"] and out["messages"] == [] and llm.requests == []
    assert run(settings, lambda s: s.get(MasterTurn, tid)).status == "skipped"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py -q -k "states or skipped"`
Expected: FAIL — нет `message.state`; `KeyError: 'skipped'`.

- [ ] **Step 3: `_play` пропускает пустой пакет**

Сразу после `new = await _player_messages(...)` в `_play`:

```python
        names = await _names(s, c)
        if not new:  # все реплики пакета отменены, пока ход начинался: модель не зовём
            turn.status, turn.finished_at = "skipped", now()
            await s.commit()
            return {"ctx": ctx, "messages": [], "names": names, "ids": [], "skipped": True}
```

и убрать прежнюю строку `names = await _names(s, c)` ниже (она переехала). В финальный `return`:

```python
        return {"ctx": ctx, "messages": [*whispers, msg], "names": names, "ids": [m.id for m in new], "skipped": False}
```

- [ ] **Step 4: `_run_turn` рассылает статусы**

Добавить метод рядом с `_status`:

```python
    async def _states(self, cid: str, ids: list[str], state: str) -> None:
        if ids:
            await self.bus.publish(cid, envelope("message.state", cid, {"ids": ids, "state": state}), None)
```

В `_run_turn`:
- ветка лимита расходов: после `await publish_message(self.bus, msg)` добавить
  `await self._states(cid, [m.id for m in new], "failed")`;
- после `turn_id = turn.id` сохранить `ids = [m.id for m in new]`, а после выхода из `async with` —
  `await self._states(cid, ids, "processing")`;
- в `try` после `published = await self._play(...)`:

```python
            if published["skipped"]:
                return turn_id
            await publish_changes(self.bus, published["ctx"], published["messages"], published["names"])
            await self._states(cid, published["ids"], "answered")
```

- в `except` после `await publish_message(self.bus, msg)`: `await self._states(cid, ids, "failed")`.

`return turn_id` внутри `try` проходит через `finally` (статус `idle` и учёт вызовов) — так и нужно.

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/Scripts/python -m pytest tests/test_pending.py tests/test_master.py tests/test_combat.py tests/test_rhythm.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agents/master.py tests/test_pending.py
git commit -m "Мастер рассылает статус реплик и пропускает опустевший пакет"
```

---

### Task 4: Клиент — типы, хранилище, запрос действий

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/stores/game.ts`
- Modify: `web/src/lib/useGameSocket.ts`
- Test: `web/src/stores/game.test.ts`, `web/src/game/game.test.ts`

**Interfaces:**
- Produces (`types.ts`): `type ReplyState = "pending" | "processing" | "answered" | "failed"`;
  `ChatMessage.state?: ReplyState | null`; `interface PendingReply { id: string; created_at: string | null }`;
  `Snapshot.pending: PendingReply | null`; `Snapshot.collect_window_sec: number`.
- Produces (`useGame`): поля `myPending: PendingReply | null`, `restored: string | null`, метод `clearRestored()`.

- [ ] **Step 1: Установить зависимости клиента (один раз)**

Run: `cd web && npm install`
Expected: `node_modules` создан, без ошибок.

- [ ] **Step 2: Написать падающие тесты**

В `web/src/stores/game.test.ts` внутрь `describe`:

```ts
  it("статус реплики, отмена и возврат текста автору", () => {
    const g = useGame.getState;
    const me = { user_id: "u1", seat_id: "s1", role: "player", is_owner: false };
    const a = { ...msg(1), kind: "action", seat_id: "s1", state: "pending" as const };
    const pending = { id: "m1", created_at: "2026-09-28T10:00:00+00:00" };
    g().apply(env("state.snapshot", { messages: [a], seats: [], replay: false, me, actions: [], blocked: {}, pending, collect_window_sec: 60 }, 1));
    expect(g().myPending).toEqual(pending);
    g().apply(env("message.state", { ids: ["m1", "чужой"], state: "processing" }));
    expect(g().messages[0].state).toBe("processing");
    g().apply(env("state.actions", { actions: [], blocked: {}, pending: null }));
    expect(g().myPending).toBeNull();
    g().apply(env("message.withdrawn", { id: "m1", seq: 1 }));
    expect(g().messages).toEqual([]);
    expect(g().restored).toBeNull();
    g().apply(env("message.withdrawn", { id: "m1", seq: 1, text: "Лезу на стену" }));
    expect(g().restored).toBe("Лезу на стену");
    g().clearRestored();
    expect(g().restored).toBeNull();
  });
```

В `web/src/game/game.test.ts` внутрь `describe`:

```ts
  it("статус и отмена реплики перезапрашивают кнопки", () => {
    const send = vi.fn(() => true);
    sideEffects(env("message.state", { ids: ["m1"], state: "answered" }), { send });
    sideEffects(env("message.withdrawn", { id: "m1", seq: 1 }), { send });
    expect(send).toHaveBeenCalledTimes(2);
  });
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `cd web && npx vitest run`
Expected: FAIL — `myPending` undefined, `send` не вызван.

- [ ] **Step 4: Типы (`web/src/lib/types.ts`)**

Перед `export interface ChatMessage`:

```ts
/** Статус реплики игрока при ИИ-мастере: ждёт хода, мастер отвечает, отвечено, не обработано. */
export type ReplyState = "pending" | "processing" | "answered" | "failed";

/** Своя реплика, ждущая хода мастера: её можно отменить. */
export interface PendingReply {
  id: string;
  created_at: string | null;
}
```

В `ChatMessage` после `created_at`: `state?: ReplyState | null;`.
В `Snapshot` после `blocked`: `pending: PendingReply | null;` и `collect_window_sec: number;`.

- [ ] **Step 5: Хранилище (`web/src/stores/game.ts`)**

- Импорт типа `PendingReply`.
- В `GameState`: `myPending: PendingReply | null; restored: string | null; clearRestored(): void;`.
  Тип `snapshot` исключает и `pending`: `Omit<Snapshot, "messages" | ... | "turn" | "pending">`.
- В `initial`: `myPending: null, restored: null,`.
- Метод: `clearRestored() { set({ restored: null }); },`.
- `state.snapshot`: деструктурировать `pending` вместе с прочими и добавить `myPending: pending ?? null` в `set`.
- `state.actions`: добавить `myPending: (p.pending as PendingReply | null) ?? null`.
- Новые ветки `switch`:

```ts
      case "message.state": {
        const ids = new Set((p.ids as string[]) ?? []);
        const state = p.state as ChatMessage["state"];
        set((s) => ({ messages: s.messages.map((m) => (ids.has(m.id) ? { ...m, state } : m)) }));
        return;
      }
      case "message.withdrawn": {
        const id = String(p.id);
        set((s) => ({
          messages: s.messages.filter((m) => m.id !== id),
          myPending: s.myPending?.id === id ? null : s.myPending,
          restored: typeof p.text === "string" ? p.text : s.restored,
        }));
        return;
      }
```

- [ ] **Step 6: Запрос действий (`web/src/lib/useGameSocket.ts`)**

```ts
const REFRESH_ACTIONS = new Set(["turn.changed", "scene.updated", "character.updated", "state.snapshot", "message.state", "message.withdrawn"]);
```

И в `sideEffects` после проверки `REFRESH_ACTIONS` — своя новая реплика тоже меняет кнопки:

```ts
  if (e.type === "message.new") {
    const m = e.payload as { seat_id?: string | null; state?: string | null };
    if (m.state === "pending" && m.seat_id && m.seat_id === useGame.getState().snapshot?.me.seat_id) sock.send("actions.get");
  }
```

- [ ] **Step 7: Прогнать тесты и проверку типов**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS, без ошибок типов.

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/types.ts web/src/stores/game.ts web/src/lib/useGameSocket.ts web/src/stores/game.test.ts web/src/game/game.test.ts
git commit -m "Клиент: статус реплики и отмена в хранилище"
```

---

### Task 5: Клиент — пометки в ленте, кнопка «Отменить», подсказка в поле ввода

**Files:**
- Modify: `web/src/game/MessageView.tsx`
- Modify: `web/src/game/Composer.tsx`
- Test: `web/src/game/game.test.ts`

**Interfaces:**
- Consumes: `ChatMessage.state`, `useGame().myPending`, `useGame().restored`, `useGame().clearRestored`,
  `snapshot.collect_window_sec` (задача 4).
- Produces: `export function waitLeft(createdAt: string | null, windowSec: number, now: number): number | null` в `Composer.tsx`.

- [ ] **Step 1: Написать падающий тест** (в `web/src/game/game.test.ts`, импорт `waitLeft` из `./Composer`)

```ts
  it("подсказка считает секунды до хода мастера", () => {
    const t0 = Date.parse("2026-09-28T10:00:00Z");
    expect(waitLeft("2026-09-28T10:00:00Z", 60, t0 + 15_000)).toBe(45);
    expect(waitLeft("2026-09-28T10:00:00Z", 60, t0 + 90_000)).toBe(0);
    expect(waitLeft(null, 60, t0)).toBeNull();
    expect(waitLeft("2026-09-28T10:00:00Z", 0, t0)).toBeNull();
  });
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd web && npx vitest run src/game/game.test.ts`
Expected: FAIL — `waitLeft` не экспортирован.

- [ ] **Step 3: Пометка статуса в `MessageView.tsx`**

Перед `export default function MessageView`:

```tsx
const STATE_TEXT = { pending: "ждёт мастера", processing: "мастер отвечает", answered: "✓", failed: "не обработано" } as const;

/** Статус реплики игрока: видят все, отменить может только автор, пока реплика ждёт хода. */
function ReplyStatus({ m, mine }: { m: ChatMessage; mine: boolean }) {
  const socket = useGame((s) => s.socket);
  if (!m.state) return null;
  return (
    <p className={`mt-1 flex items-center gap-2 text-xs ${m.state === "failed" ? "text-warn" : "text-muted"}`}>
      <span>{STATE_TEXT[m.state]}</span>
      {mine && m.state === "pending" && (
        <button type="button" className="underline" onClick={() => socket?.send("message.withdraw", { message_id: m.id })}>
          Отменить
        </button>
      )}
    </p>
  );
}
```

Импорт: `import { useGame } from "../stores/game";`.

Вставить `<ReplyStatus m={m} mine={m.seat_id === who.mySeat} />`:
- в ветке шёпота игрока — после `<p className="font-narration">…</p>` (только если `!fromMaster`);
- в общей ветке (действие/речь) — после абзаца с текстом, внутри блока `rounded-lg`, как `<ReplyStatus m={m} mine={mine} />`.

- [ ] **Step 4: Подсказка и возврат текста в `Composer.tsx`**

Функция рядом с `secondsLeft`:

```ts
/** Секунд до хода мастера по окну сбора реплик; null — окна нет или время неизвестно. */
export function waitLeft(createdAt: string | null, windowSec: number, now: number): number | null {
  if (!createdAt || !windowSec) return null;
  return Math.max(0, Math.round((Date.parse(createdAt) + windowSec * 1000 - now) / 1000));
}
```

В компоненте: взять из `useGame()` ещё `myPending, restored, clearRestored`;

```ts
  const nowWait = useNow(!!myPending);
  const wait = myPending ? waitLeft(myPending.created_at, snapshot?.collect_window_sec ?? 0, nowWait) : null;

  // отменённая реплика возвращается в поле, чтобы её поправить
  useEffect(() => {
    if (restored === null) return;
    if (!useDraft.getState().text) useDraft.getState().setText(restored);
    clearRestored();
  }, [restored, clearRestored]);
```

(Хуки — до раннего `return`, рядом с остальными `useEffect`.)

Под блоком `notice` добавить:

```tsx
      {myPending && (
        <p className="text-xs text-muted" role="status">
          Ответ мастера — когда напишут все{wait ? ` или примерно через ${wait} с` : ""}.
        </p>
      )}
```

Причину из `blocked["chat.play"]` поле уже показывает (`hint`), поле ввода не блокируется.

- [ ] **Step 5: Прогнать тесты, типы и сборку**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS, сборка без ошибок.

- [ ] **Step 6: Commit**

```bash
git add web/src/game/MessageView.tsx web/src/game/Composer.tsx web/src/game/game.test.ts
git commit -m "Клиент: статус реплики, кнопка «Отменить» и подсказка до хода мастера"
```

---

### Task 6: Проверка целиком

**Files:** —

- [ ] **Step 1: Весь серверный набор**

Run: `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider --deselect tests/test_content.py`
Expected: PASS. (`test_content.py` на Windows падает из-за прав на симлинки — известная проблема, не относится к задаче.)

- [ ] **Step 2: Линтер**

Run: `.venv/Scripts/python -m ruff check app tests`
Expected: без замечаний.

- [ ] **Step 3: Клиент**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS.

- [ ] **Step 4: Живая проверка**

Run: `docker compose up -d --build app`
Вручную: кампания с ИИ-мастером и двумя игроками. Игрок 1 пишет действие: у реплики «ждёт мастера» и «Отменить», над полем причина и «примерно через N с»; вторая реплика не уходит; `// текст` уходит. «Отменить» — реплика исчезает у обоих, текст в поле. Игрок 2 пишет — у обеих реплик «мастер отвечает», затем «✓».

- [ ] **Step 5: Commit** — если в шагах 1-4 что-то правилось.
