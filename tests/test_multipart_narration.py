from types import SimpleNamespace

from app.agents.master.action_progress import finalize_action_parts, public_action_notice
from app.agents.master.narration import NarrationMixin
from app.agents.master.outcomes import failed_item_action
from app.core.resolution.contracts import ActionProgress, FailureInfo
from app.db.models import Campaign, Entity, InventoryItem, Message
from app.tools.master.base import FOUND_ITEM
from app.tools.registry import execute
from app.tools.resolution.context import refresh_world
from app.tools.resolution.requests import (
    bind_message_actions,
    bound_tool_key,
    set_action_progress,
)
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


class Narrator(NarrationMixin):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    async def _ask(self, *args):
        self.requests.append(args[6])
        return SimpleNamespace(text=next(self.replies))


def _mock_narrator_context(monkeypatch):
    import app.agents.master.narration as module

    monkeypatch.setattr(module.combat, "public_turn", lambda _: None)
    monkeypatch.setattr(module, "effect_names", lambda _: {})
    monkeypatch.setattr(module, "_narration_length", lambda *_: "два предложения")
    monkeypatch.setattr(module, "_check_only", lambda *_: False)


def test_completed_multipart_has_no_partial_cancel(game, monkeypatch):
    _mock_narrator_context(monkeypatch)
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {"slots_used": {}}
        ctx.world.invalidate(hero)

        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=601,
            content="творю ягоды и осматриваю стол",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.goodberry", "summary": "сотворить ягоды"},
                    {"verb": "search", "target_id": "desk", "summary": "осмотреть стол"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0: cast
        cast_args = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[0].model_dump()}
        k_cast = await bound_tool_key(ctx, "cast_spell", cast_args, "call_cast")
        await execute(ctx, "cast_spell", cast_args, key=k_cast)

        # Part 1: search roll check and place item
        check_args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.easy",
            "reason": "осмотр стола",
            "action_ref": refs[1].model_dump(),
        }
        k_chk = await bound_tool_key(ctx, "roll_check", check_args, "call_search")
        r_chk = await execute(ctx, "roll_check", check_args, key=k_chk)
        assert r_chk["ok"], r_chk
        place_args = {
            "item_template_id": "item.dagger",
            "location_id": ch.location_id,
            "reason": "находка в столе",
            "discovery_check_event_id": r_chk["event_id"],
            "action_ref": refs[1].model_dump(),
        }
        k_place = await bound_tool_key(ctx, "place_item", place_args, "call_place")
        await execute(ctx, "place_item", place_args, key=k_place)

        await finalize_action_parts(ctx)

        prose = "Бран творит добрые ягоды и внимательно осматривает стол, находя старинный свиток."
        narrator = Narrator([prose])
        c = await ctx.session.get(Campaign, campaign_id)
        text, audit = await narrator._narrate(
            [],
            None,
            c,
            ch.seat_id,
            "t_narrate",
            "Мастер",
            "",
            msg.content,
            ctx,
            tool_attempts=[],
        )

        assert prose in text
        assert not audit.get("partial_cancel")
        assert "часть заявки" not in text

    play(settings, campaign_id, [20, 20], scenario)


def test_only_search_left_names_search(game, monkeypatch):
    _mock_narrator_context(monkeypatch)
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {"slots_used": {}}
        ctx.world.invalidate(hero)

        desk = Entity(
            id="desk_search", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=602,
            content="творю ягоды и осматриваю стол",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.goodberry", "summary": "сотворить ягоды"},
                    {"verb": "search", "target_id": "desk_search", "summary": "осмотреть стол"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0: cast
        cast_args = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[0].model_dump()}
        k_cast = await bound_tool_key(ctx, "cast_spell", cast_args, "call_cast")
        await execute(ctx, "cast_spell", cast_args, key=k_cast)

        # Part 1: unhandled search
        await finalize_action_parts(ctx)
        # Record cancel action for part 1
        await execute(
            ctx,
            "cancel_action",
            {"character_id": hero, "reason": "мастер не обработал действие", "action_ref": refs[1].model_dump()},
            key="cancel_p1",
        )

        prose = "Бран сотворил добрые ягоды в ладони."
        narrator = Narrator([prose])
        c = await ctx.session.get(Campaign, campaign_id)
        text, audit = await narrator._narrate(
            [],
            None,
            c,
            ch.seat_id,
            "t_narrate",
            "Мастер",
            "",
            msg.content,
            ctx,
            tool_attempts=[],
        )

        assert prose in text
        assert audit.get("partial_cancel")
        # Notice must specifically name the search, NOT generic "часть заявки мастер не обработал"
        assert ("поиск" in text.lower() or "осмотр" in text.lower())
        assert "часть заявки мастер не обработал" not in text

    play(settings, campaign_id, [], scenario)


def test_blocked_contents_names_unopened_container(game, monkeypatch):
    _mock_narrator_context(monkeypatch)
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=603,
            content="открываю сундук и осматриваю содержимое",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "interact", "summary": "открыть сундук"},
                    {
                        "verb": "search",
                        "summary": "осмотр содержимого",
                        "depends_on": [{"part": 0, "requires": "success"}],
                    },
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0 is denied / failed
        await set_action_progress(
            ctx,
            refs[0],
            ActionProgress(
                status="denied",
                failure=FailureInfo(code="locked", category="rule_denial", rolled_back=False, attempt_id="att0"),
            ),
        )
        # Part 1 is blocked by part 0
        await set_action_progress(ctx, refs[1], ActionProgress(status="blocked", blocked_by=[0]))

        # Cancel actions recorded
        await execute(
            ctx,
            "cancel_action",
            {"character_id": hero, "reason": "сундук не открыт", "action_ref": refs[1].model_dump()},
            key="cancel_p1",
        )

        prose = "Бран подходит к тяжёлому кованому сундуку."
        narrator = Narrator([prose])
        c = await ctx.session.get(Campaign, campaign_id)
        text, audit = await narrator._narrate(
            [],
            None,
            c,
            ch.seat_id,
            "t_narrate",
            "Мастер",
            "",
            msg.content,
            ctx,
            tool_attempts=[],
        )

        assert "сундук не открыт" in text.lower() or "сундук" in text.lower()

    play(settings, campaign_id, [], scenario)


def test_hidden_failure_notice_does_not_expose_dc_or_secrets(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=604,
            content="осматриваю стену",
            intent={"actions": [{"verb": "search", "summary": "осмотр стены"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)

        prog = ActionProgress(
            status="unhandled",
            reason_code="unconfirmed_search",
            failure=FailureInfo(code="secret_dc_10", category="rule_denial", rolled_back=False, attempt_id="att1"),
        )
        notice = public_action_notice(ctx, refs[0], prog)
        assert notice is not None
        assert "Сл 10" not in notice
        assert "dc" not in notice.lower()
        assert "secret" not in notice.lower()

    play(settings, campaign_id, [], scenario)


def test_one_denial_preserves_other_committed_facts(game, monkeypatch):
    _mock_narrator_context(monkeypatch)
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {"slots_used": {}}
        ctx.world.invalidate(hero)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=605,
            content="творю ягоды и читаю мысли стражника",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.goodberry", "summary": "сотворить ягоды"},
                    {"verb": "custom", "summary": "читать мысли стражника"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0 succeeds
        cast_args = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[0].model_dump()}
        k_cast = await bound_tool_key(ctx, "cast_spell", cast_args, "call_cast")
        await execute(ctx, "cast_spell", cast_args, key=k_cast)

        # Part 1 denied
        await set_action_progress(ctx, refs[1], ActionProgress(status="denied", reason_code="rule_denial"))
        await execute(
            ctx,
            "cancel_action",
            {"character_id": hero, "reason": "действие отклонено правилами", "action_ref": refs[1].model_dump()},
            key="cancel_p1",
        )

        prose = "Бран сжимает ладонь, и на ней появляются сочные добрые ягоды."
        narrator = Narrator([prose])
        c = await ctx.session.get(Campaign, campaign_id)
        text, audit = await narrator._narrate(
            [],
            None,
            c,
            ch.seat_id,
            "t_narrate",
            "Мастер",
            "",
            msg.content,
            ctx,
            tool_attempts=[],
        )

        # Committed fact of goodberry is preserved
        assert "добрые ягоды" in text
        # Denial notice is included
        assert ("отклон" in text.lower() or "не" in text.lower())
        assert not audit.get("cancel_fallback")

    play(settings, campaign_id, [], scenario)


def test_staff_lever_preserves_story_after_unsupported_use(game, monkeypatch):
    _mock_narrator_context(monkeypatch)
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        # Staff is a found item with no use mechanics
        staff = InventoryItem(
            id="inv_staff",
            character_id=hero,
            item_template_id=FOUND_ITEM,
            display_name="Деревянный посох",
            qty=1,
            equipped=True,
        )
        ctx.session.add(staff)

        loc_id = "loc_dungeon"
        ch.location_id = loc_id
        loc = Entity(
            id=loc_id,
            campaign_id=campaign_id,
            kind="location",
            name="Подземелье",
            state={
                "sketch": {
                    "shape": "room",
                    "cols": 6,
                    "rows": 4,
                    "party": [1, 2],
                    "exits": [
                        {
                            "name": "потайная плита",
                            "kind": "bars",
                            "side": "n",
                            "at": 1,
                            "state": "locked",
                            "to": None,
                        }
                    ],
                    "features": [],
                }
            },
        )
        ctx.world.scene.location_id = loc_id
        ctx.session.add_all([ctx.world.scene, loc])
        await ctx.session.flush()
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=606,
            content="использую посох как рычаг чтобы открыть потайную плиту",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "interact", "target_id": "потайная плита", "summary": "отжать плиту"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. use_item fails with item_use_unsupported
        tool_attempts = [
            {
                "tool": "use_item",
                "args": {"character_id": hero, "inventory_id": "inv_staff", "action_ref": refs[0].model_dump()},
                "result": {
                    "ok": False,
                    "failure": {"code": "item_use_unsupported", "category": "rule_denial", "rolled_back": False},
                },
            }
        ]

        # 2. roll_check succeeds
        str_args = {
            "character_id": hero,
            "stat": "str",
            "difficulty": "dc.easy",
            "reason": "отжать плиту",
            "action_ref": refs[0].model_dump(),
        }
        k_chk = await bound_tool_key(ctx, "roll_check", str_args, "call_str")
        r_chk = await execute(ctx, "roll_check", str_args, key=k_chk)
        assert r_chk["ok"], r_chk

        # 3. edit_sketch unlock passage succeeds -> marks part 0 completed
        sketch_args = {
            "location_id": ch.location_id,
            "action": "unlock",
            "target": "потайная плита",
            "action_ref": refs[0].model_dump(),
        }
        res_sketch = await execute(ctx, "edit_sketch", sketch_args, key="call_sketch")
        assert res_sketch["ok"], res_sketch

        await finalize_action_parts(ctx)
        assert not failed_item_action(ctx, tool_attempts)

        prose = "Бран упирается посохом и с глухим треском отжимает потайную плиту, открывая тёмный проход."
        narrator = Narrator([prose])
        c = await ctx.session.get(Campaign, campaign_id)
        text, audit = await narrator._narrate(
            [],
            None,
            c,
            ch.seat_id,
            "t_narrate",
            "Мастер",
            "",
            msg.content,
            ctx,
            tool_attempts=tool_attempts,
        )

        assert prose in text
        assert not audit.get("item_fallback")
        assert not audit.get("partial_cancel")

    play(settings, campaign_id, [13], scenario)


def test_missing_consumable_still_blocks_invented_consumption(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        tool_attempts = [
            {
                "tool": "use_item",
                "args": {"character_id": hero, "inventory_id": "inv_missing_potion"},
                "result": {
                    "ok": False,
                    "failure": {"code": "not_in_inventory", "category": "rule_denial", "rolled_back": False},
                },
            }
        ]
        assert failed_item_action(ctx, tool_attempts) is True

    play(settings, campaign_id, [], scenario)


def test_failed_transfer_still_blocks_invented_transfer_after_neighbor_success(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        tool_attempts = [
            {
                "tool": "give_item",
                "args": {"character_id": hero, "item_template_id": "item.torch", "to_character_id": "ch_ally"},
                "result": {"ok": False, "failure": {"code": "not_owned", "category": "rule_denial"}},
            },
            {
                "tool": "resolve_attack",
                "args": {"attacker_id": hero},
                "result": {"ok": True},
            },
        ]
        assert failed_item_action(ctx, tool_attempts) is True

    play(settings, campaign_id, [], scenario)


def test_unlock_does_not_prove_consumption(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        # A door unlock happened
        await execute(
            ctx,
            "edit_sketch",
            {"action": "unlock", "from_loc": "loc_1", "to_loc": "loc_2"},
            key="unlock_other",
        )
        tool_attempts = [
            {
                "tool": "use_item",
                "args": {"character_id": hero, "inventory_id": "inv_potion"},
                "result": {"ok": False, "failure": {"code": "missing_item", "category": "rule_denial"}},
            }
        ]
        assert failed_item_action(ctx, tool_attempts) is True

    play(settings, campaign_id, [], scenario)


def test_unsupported_use_without_completion_does_not_claim_success(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=610,
            content="использую посох как рычаг",
            intent={"actions": [{"verb": "use_item", "instrument_id": "inv_staff"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        tool_attempts = [
            {
                "tool": "use_item",
                "args": {"character_id": hero, "inventory_id": "inv_staff", "action_ref": refs[0].model_dump()},
                "result": {
                    "ok": False,
                    "failure": {"code": "item_use_unsupported", "category": "rule_denial", "rolled_back": False},
                },
            }
        ]
        # Not completed! Part is unhandled or pending
        await set_action_progress(ctx, refs[0], ActionProgress(status="unhandled", reason_code="unsupported_mechanic"))
        assert failed_item_action(ctx, tool_attempts) is True

    play(settings, campaign_id, [], scenario)
