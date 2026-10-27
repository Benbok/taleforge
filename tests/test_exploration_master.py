import asyncio
import json

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.db.models import Event, HeroAbility, MasterTurn, Message
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def proposal():
    return dict(
        schema_version=2,
        name="Искры",
        source="supernatural",
        resolution="automatic",
        intensity="light",
        effects=[{"kind": "cosmetic"}],
    )


def test_fresh_v2_magic_has_real_cost_learning_and_automatic_card(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            assert len(list(await s.scalars(select(HeroAbility)))) == 1
            card = await s.scalar(select(Message).where(Message.kind == "roll"))
            assert card and card.data["universal_proof"]["cost"] == "1"
            assert card.data["universal_proof"]["draws"] == []
            assert card.data["universal_proof"]["source_kind"] == "supernatural"
        assert "HIDDEN-SECRET" not in json.dumps(provider.prompts[-2:])
        await engine.dispose()

    asyncio.run(run())


def test_fresh_legacy_proposal_cannot_bypass_review_or_spend(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                {"kind": "ability", "profile": {"id": "bad", "kind": "check", "attribute": "wis"}},
                {"kind": "ordinary_check"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            events = list(await s.scalars(select(Event)))
            # Nothing of the legacy proposal is used: the floor is a plain turn that costs nothing.
            assert [op["kind"] for e in events for op in e.payload["proposal"]["operations"]] == ["wait"]
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "24"
            turn = await s.get(MasterTurn, tid)
            assert turn.trace["proposal_attempts"]["source"] == 2
        await engine.dispose()

    asyncio.run(run())


def test_mismatch_review_does_not_roll_and_budget_is_durable(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [proposal(), {"verdict": "mismatch", "message": "Нужна форма, а не искры."}, RuntimeError("offline")]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        await MasterService(maker, Bus(), Provider([])).run_turn("c")
        async with maker() as s:
            assert list(await s.scalars(select(Event))) == []
            assert (await s.get(MasterTurn, tid)).trace["proposal_attempts"]["source"] == 2
        await engine.dispose()

    asyncio.run(run())


def test_unrealized_narrative_effects_fall_back_without_repeating_magic(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                proposal(),
                {"verdict": "pass"},
                "Герой стал неуязвимым кустом.",
                {"verdict": "mismatch", "message": "Не применялась форма."},
                "Появилась золотая кружка.",
                {"verdict": "mismatch", "message": "Не создан предмет."},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            message = await s.get(Message, turn.narration_message_id)
            assert "неуязвим" not in message.content and "золотая" not in message.content
            assert len(list(await s.scalars(select(Event)))) == 1
            assert turn.trace["exploration_narration"]["attempts"] == 2
        await engine.dispose()

    asyncio.run(run())


def test_provider_tool_schema_omits_array_length_limits_but_model_still_enforces_them():
    import pytest
    from pydantic import ValidationError

    from app.agents.master.universal import provider_schema
    from app.rules.universal.exploration import IntentV2

    schema = provider_schema(IntentV2)

    def keys(node):
        if isinstance(node, dict):
            yield from node
            for value in node.values():
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    assert not {"minItems", "maxItems"} & set(keys(schema))
    assert "$defs" in schema  # the rest of the closed schema is retained
    with pytest.raises(ValidationError):
        IntentV2.model_validate({**proposal(), "effects": [{"kind": "cosmetic"}] * 17})


def test_repair_request_names_the_actual_rejection_reason(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        clashing = {
            **proposal(),
            "requirements": [
                {"id": "same", "quote": "Invent", "effect": "cosmetic"},
                {"id": "same", "quote": "vine", "effect": "cosmetic"},
            ],
        }
        provider = Provider(
            [
                clashing,
                {"verdict": "pass", "covered_requirements": ["same"]},
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        repair = json.loads(provider.prompts[2][-1]["content"])["repair"]
        assert "не покрыла требования" in repair
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
        await engine.dispose()

    asyncio.run(run())


def test_unavailable_object_reference_is_repaired_not_reported_as_provider_failure(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        ghost = {**proposal(), "effects": [{"kind": "cosmetic", "object_id": "ghost"}]}
        provider = Provider(
            [
                ghost,
                {"verdict": "pass", "covered_requirements": []},
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        repair = json.loads(provider.prompts[2][-1]["content"])["repair"]
        assert "Предмет недоступен" in repair
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
        await engine.dispose()

    asyncio.run(run())


def test_only_the_models_ordinary_declaration_with_ordinary_effects_skips_the_review(tmp_path):
    from app.core.universal.interpretation import is_plain_action
    from app.rules.universal.exploration import EffectIntentV2, IntentV2

    def intent(kind="move", source="mundane", **extra):
        return IntentV2(source=source, resolution="automatic", effects=[EffectIntentV2(kind=kind)], **extra)

    assert is_plain_action(intent(player_request="ordinary"))
    assert not is_plain_action(intent())  # an undeclared request is reviewed
    for declared in ("supernatural", "pretend", "unclear"):
        assert not is_plain_action(intent(player_request=declared))
    assert not is_plain_action(intent(source="supernatural", kind="cosmetic", player_request="ordinary"))
    assert not is_plain_action(intent(kind="change_form", player_request="ordinary"))


def test_lack_of_energy_is_explained_to_the_player_after_one_repair_attempt(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "2"}}
            await s.commit()
        costly = dict(
            schema_version=2,
            source="supernatural",
            player_request="supernatural",
            resolution="automatic",
            intensity="normal",
            effects=[{"kind": "cosmetic"}],
        )
        review = {"verdict": "pass", "covered_requirements": []}
        provider = Provider([costly, review, costly, "Сил не хватило.", {"verdict": "pass"}])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        repair = json.loads(provider.prompts[2][-1]["content"])["repair"]
        assert "нужно 3" in repair and "есть 2" in repair  # the model is told the real numbers and may choose less
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == "Сил не хватило."
            assert "не хватает 1" in narrate_prompt(provider)
            assert list(await s.scalars(select(Event))) == []
        await engine.dispose()

    asyncio.run(run())


def test_structured_calls_leave_room_for_a_thinking_models_reasoning(tmp_path):
    class Recording(Provider):
        def __init__(self, replies):
            super().__init__(replies)
            self.budgets = []

        async def complete(self, messages, **kwargs):
            self.budgets.append(kwargs.get("max_tokens"))
            return await super().complete(messages, **kwargs)

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Recording(
            [
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        # decision, meaning review and narration review are tool calls; their answer must not be cut off
        structured = [provider.budgets[0], provider.budgets[1], provider.budgets[3]]
        assert all(budget is not None and budget >= 16000 for budget in structured), provider.budgets
        await engine.dispose()

    asyncio.run(run())


def test_leaving_the_bush_form_is_a_free_dismissal_of_the_effect_the_model_can_see(tmp_path):
    from app.core.universal.effects import active_effects, start_effect
    from app.db.models import Character
    from app.rules.universal.exploration import EffectIntentV2

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            s.add(Event(id="form", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            form = await start_effect(
                s, "c", "hero", "hero", "form", "0", EffectIntentV2(kind="change_form", lifetime="timed"), 0, 18
            )
            energy = (await s.get(Character, "hero")).resources["energies"]["wis"]
            await s.commit()
        dismissal = dict(
            schema_version=2,
            source="mundane",
            player_request="ordinary",
            resolution="automatic",
            effects=[{"kind": "dismiss", "effect_id": form.id}],
        )
        provider = Provider([dismissal, "Куст оседает, и вы снова становитесь собой.", {"verdict": "pass"}])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        seen = json.loads(provider.prompts[0][-1]["content"])["active_effects"]
        assert [e["id"] for e in seen] == [form.id] and seen[0]["kind"] == "change_form"
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert not await active_effects(s, "c", "hero")
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == energy  # nothing is paid
        await engine.dispose()

    asyncio.run(run())


def test_voiced_narration_is_stored_where_the_player_reads_it(tmp_path):
    from app.db.models import Campaign

    class FakeTTS:
        enabled = True

        def get_engine(self, provider):
            return self

        async def voice_for_narration(self, media_dir, campaign_id, text, provider=None, voice_name=None):
            return {"id": "v1", "duration": 3.5}

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
            campaign.settings = {**(campaign.settings or {}), "tts_enabled": True, "tts_text_enabled": True}
            await s.commit()
        provider = Provider(
            [
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        service = MasterService(maker, Bus(), provider, tts=FakeTTS(), media_dir=tmp_path)
        tid = await service.run_turn("c")
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            # the chat's player reads voices/voice/voice_parts, as the old master wrote them
            assert message.data["voice"] == {"id": "v1", "duration": 3.5}
            assert message.data["voices"] == [{"id": "v1", "duration": 3.5}] and message.data["voice_parts"] == 1
        await engine.dispose()

    asyncio.run(run())


def test_the_energy_shortage_stays_the_answer_when_the_repair_attempt_fails_otherwise(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "2"}}
            await s.commit()
        costly = dict(
            schema_version=2,
            source="supernatural",
            player_request="supernatural",
            resolution="automatic",
            intensity="normal",
            effects=[{"kind": "cosmetic"}],
        )
        broken = {
            **costly,
            "intensity": "light",
            "requirements": [{"id": "r", "quote": "нет такой цитаты", "effect": "cosmetic"}],
        }
        review = {"verdict": "pass", "covered_requirements": ["r"]}
        story = "Сил не хватило даже на малую долю замысла."
        provider = Provider(
            [costly, {"verdict": "pass", "covered_requirements": []}, broken, review, story, {"verdict": "pass"}]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == story
            # the shortfall stays the fact told, not the vague failure of the second attempt
            assert "не хватает 1" in narrate_prompt(provider)
        await engine.dispose()

    asyncio.run(run())


def bridge(scale="tiny"):
    return dict(
        schema_version=2,
        name="Мост",
        source="supernatural",
        player_request="supernatural",
        resolution="automatic",
        effects=[
            {
                "kind": "create_object",
                "template": "structure",
                "scale": scale,
                "lifetime": "timed",
                "label": "Мост",
            }
        ],
    )


def test_laws_powers_and_world_reach_the_decision_and_the_meaning_review_but_never_the_narration_or_the_secret_notes(
    tmp_path,
):
    from app.db.models import CampaignSecret

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            secret = await s.get(CampaignSecret, "c")
            secret.setting = {
                "studio": {
                    "laws": "NO TIME TRAVEL",
                    "powers": "Магия природы живёт в корнях.",
                    "world": "Подземное царство теней.",
                    "private": "HIDDEN-SECRET",
                }
            }
            await s.commit()
        provider = Provider(
            [
                bridge("large"),
                {"verdict": "pass", "covered_requirements": []},
                "Мост перекидывается через пропасть.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        rules = {
            "laws": "NO TIME TRAVEL",
            "powers": "Магия природы живёт в корнях.",
            "world": "Подземное царство теней.",
        }
        assert json.loads(provider.prompts[0][-1]["content"])["world_rules"] == rules
        review = provider.prompts[1][-1]["content"]
        assert "NO TIME TRAVEL" in review and "Магия природы живёт в корнях." in review
        assert "HIDDEN-SECRET" not in review
        # the narration and its review work from saved facts: the laws can hold an author's secrets
        assert "NO TIME TRAVEL" not in json.dumps(provider.prompts[2:])
        assert "HIDDEN-SECRET" not in json.dumps(provider.prompts[2:])
        await engine.dispose()

    asyncio.run(run())


def test_a_forbidden_verdict_spends_nothing_and_is_not_a_repair_loop(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        why = "В этом мире мёртвых не воскрешают."
        provider = Provider(
            [bridge("large"), {"verdict": "forbidden", "message": why}, "Так не бывает.", {"verdict": "pass"}]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        decisions = [p for p in provider.prompts if "Интерпретируй" in p[0]["content"]]
        assert len(decisions) == 1  # no second attempt: the world simply does not allow it
        async with maker() as s:
            assert list(await s.scalars(select(Event))) == []
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "24"
            assert (await s.get(MasterTurn, tid)).trace["intent_reviews"]
        await engine.dispose()

    asyncio.run(run())


def test_an_unsupported_verdict_asks_the_model_to_use_a_free_effect(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        review = {"verdict": "unsupported", "message": "Нет вида для остановки существ."}
        provider = Provider([bridge("large"), review, bridge("large"), review, "Не вышло.", {"verdict": "pass"}])
        await MasterService(maker, Bus(), provider).run_turn("c")
        assert "free_effect" in json.loads(provider.prompts[2][-1]["content"])["repair"]
        await engine.dispose()

    asyncio.run(run())


def test_a_reviewer_who_finds_the_scale_implausible_stops_the_spell_and_tells_the_model_why(tmp_path):

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        why = "Мост через пропасть не может быть крошечным."
        provider = Provider(
            [
                bridge("tiny"),
                {"verdict": "mismatch", "message": why},
                bridge("tiny"),  # the same answer again: its review is already known, so no second review call
                "Магия не слушается.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        assert why in json.loads(provider.prompts[2][-1]["content"])["repair"]
        async with maker() as s:
            # The floor records the words as a free effect: it makes no bridge and opens no place beyond it.
            events = list(await s.scalars(select(Event)))
            assert [op["kind"] for e in events for op in e.payload["proposal"]["operations"]] == ["free_effect"]
            assert (await s.get(MasterTurn, tid)).status == "done"
        await engine.dispose()

    asyncio.run(run())


def test_a_walk_that_names_no_structure_is_reviewed_where_a_crossable_one_stands():
    from app.core.universal.interpretation import is_plain_action
    from app.rules.universal.exploration import EffectIntentV2, IntentV2

    def walk(**effect):
        return IntentV2(
            source="mundane",
            player_request="ordinary",
            resolution="automatic",
            effects=[EffectIntentV2(kind="move", **effect)],
        )

    assert is_plain_action(walk())  # no bridge around: plain walking
    assert not is_plain_action(walk(), crossable=True)  # a bridge stands here and the walk names none: ask the reviewer
    assert is_plain_action(walk(object_id="en_bridge"), crossable=True)


def test_the_master_is_shown_what_each_running_effect_says_and_what_each_created_being_can_do(tmp_path):
    from app.core.universal.effects import start_effect
    from app.core.universal.objects import ObjectState, store
    from app.db.models import Entity
    from app.rules.universal.exploration import EffectIntentV2

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            s.add(Event(id="fx", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            doll = Entity(id="en_doll", campaign_id="c", kind="object", name="Глиняный человечек", state={})
            store(doll, ObjectState(template="creature", controller_id="hero", abilities="Ходит и носит лёгкое."))
            s.add(doll)
            await s.flush()
            await start_effect(
                s,
                "c",
                "hero",
                "hero",
                "fx",
                "0",
                EffectIntentV2(
                    kind="free_effect",
                    label="Скелеты остановлены",
                    appearance="Костяные силуэты замерли.",
                    lifetime="timed",
                ),
                0,
                60,
            )
            await s.commit()
        provider = Provider(
            [proposal(), {"verdict": "pass", "covered_requirements": []}, "Искры.", {"verdict": "pass"}]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        context = json.loads(provider.prompts[0][-1]["content"])
        effect = context["active_effects"][0]
        assert effect["label"] == "Скелеты остановлены" and effect["description"] == "Костяные силуэты замерли."
        being = next(o for o in context["objects"] if o["id"] == "en_doll")
        assert being["template"] == "creature" and being["abilities"] == "Ходит и носит лёгкое."
        await engine.dispose()

    asyncio.run(run())


def narrate_prompt(provider):
    """The facts the writer was given: the call whose system prompt asks for a continuation of the scene."""
    return next(p for p in provider.prompts if "Расскажи продолжение сцены" in p[0]["content"])[-1]["content"]


def test_a_shortfall_is_told_in_the_story_with_how_much_was_missing(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "2"}}
            await s.commit()
        costly = dict(
            schema_version=2,
            source="supernatural",
            player_request="supernatural",
            resolution="automatic",
            intensity="normal",
            effects=[{"kind": "cosmetic"}],
        )
        story = "Ты тужишься, но сил не хватает: глина остаётся глиной."
        provider = Provider(
            [costly, {"verdict": "pass", "covered_requirements": []}, costly, story, {"verdict": "pass"}]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        assert "не хватает 1" in narrate_prompt(provider)
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == story  # the master's own words, not a service phrase
            assert list(await s.scalars(select(Event))) == []
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "2"
        await engine.dispose()

    asyncio.run(run())


def test_a_law_that_forbids_is_told_in_the_story(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        why = "Мёртвых в этом мире не воскрешают."
        story = "Магия откликается лишь эхом: мёртвые здесь остаются мёртвыми."
        provider = Provider([bridge("large"), {"verdict": "forbidden", "message": why}, story, {"verdict": "pass"}])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        assert why in narrate_prompt(provider)
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == story and list(await s.scalars(select(Event))) == []
        await engine.dispose()

    asyncio.run(run())


def test_exhausted_repairs_are_told_in_the_story_not_as_invalid_parameters(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        broken = dict(
            schema_version=2,
            source="supernatural",
            player_request="supernatural",
            resolution="automatic",
            intensity="light",
            requirements=[{"id": "r", "quote": "нет такой цитаты", "effect": "cosmetic"}],
            effects=[{"kind": "cosmetic"}],
        )
        story = "Магия не слушается: замысел рассыпается, не успев начаться."
        provider = Provider(
            [broken, {"verdict": "pass", "covered_requirements": ["r"]}, broken, story, {"verdict": "pass"}]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == story
            assert "некорректные параметры" not in json.dumps(provider.prompts, ensure_ascii=False)
        await engine.dispose()

    asyncio.run(run())


def test_only_technical_failures_stay_plain_notices_the_rest_go_into_the_story():
    from app.agents.master.action_results import narration_parts

    def outcome(category):
        return {"status": "denied", "failure": {"category": category, "code": "x", "message": category}}

    story, notices = narration_parts(
        {
            "a": outcome("insufficient_resources"),
            "b": outcome("world_denial"),
            "c": outcome("invalid_proposal"),
            "d": outcome("roll_failed"),
            "e": outcome("internal_error"),
            "f": {"status": "applied"},
        }
    )
    assert sorted(story) == ["a", "b", "c", "d", "f"] and notices == ["internal_error"]


def unrealisable(source):
    """A proposal that is well formed but never compiles: the quote it relies on is not in the player's words."""
    return dict(
        schema_version=2,
        source=source,
        player_request="supernatural" if source == "supernatural" else "ordinary",
        resolution="automatic",
        intensity="light",
        requirements=[{"id": "r", "quote": "нет такой цитаты", "effect": "cosmetic"}],
        effects=[{"kind": "cosmetic"}],
    )


def test_a_magic_request_the_model_cannot_shape_is_kept_as_a_free_effect(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        story = "Магия откликается, но по-своему: вокруг героя вспыхивают светлячки."
        broken = unrealisable("supernatural")
        provider = Provider([broken, {"verdict": "pass", "covered_requirements": ["r"]}, broken, story, {"verdict": "pass"}])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            events = list(await s.scalars(select(Event)))
            assert len(events) == 1  # the words are recorded, not refused
            kinds = [op["kind"] for op in events[0].payload["proposal"]["operations"]]
            assert kinds == ["free_effect"]
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "23"  # a tiny effect: one start
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert message.content == story
        assert "не слушается" not in json.dumps(provider.prompts, ensure_ascii=False)
        await engine.dispose()

    asyncio.run(run())


def test_an_ordinary_request_the_model_cannot_shape_is_a_plain_turn_that_costs_nothing(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        story = "Доска занимается неохотно, но тесак высекает искру."
        broken = unrealisable("mundane")
        provider = Provider([broken, {"verdict": "pass", "covered_requirements": ["r"]}, broken, story, {"verdict": "pass"}])
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            events = list(await s.scalars(select(Event)))
            assert len(events) == 1
            assert events[0].payload["proposal"]["definition"]["source"] == "mundane"
            # The deed leaves a remembered note, and costs nothing: it is not magic.
            assert [op["kind"] for op in events[0].payload["proposal"]["operations"]] == ["free_effect"]
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "24"
        await engine.dispose()

    asyncio.run(run())


def test_an_ordinary_deed_the_model_cannot_shape_is_still_rolled_on_the_ability_it_named(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        broken = {**unrealisable("mundane"), "attribute": "str", "difficulty": 15}
        review = {"verdict": "pass", "covered_requirements": ["r"]}
        provider = Provider([broken, review, broken, "Камень не уступил.", {"verdict": "pass"}])
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            proposal = (await s.scalars(select(Event))).one().payload["proposal"]
            assert proposal["resolution"] == "check"  # a risky deed never succeeds just because the model slipped
            assert proposal["attribute"] == "str" and proposal["difficulty"] == 15
        await engine.dispose()

    asyncio.run(run())


def test_the_not_realised_fact_does_not_blame_magic_for_an_ordinary_deed():
    from app.agents.master.exploration import not_realised_fact

    assert "магия" not in not_realised_fact().message.casefold()


def test_a_request_that_was_magic_on_any_attempt_stays_magic_when_the_model_backs_down(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        first, second = unrealisable("supernatural"), unrealisable("mundane")
        provider = Provider(
            [
                first,
                {"verdict": "pass", "covered_requirements": ["r"]},
                second,
                {"verdict": "pass", "covered_requirements": ["r"]},
                "Светлячки вспыхивают.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            events = list(await s.scalars(select(Event)))
            assert [op["kind"] for e in events for op in e.payload["proposal"]["operations"]] == ["free_effect"]
        await engine.dispose()

    asyncio.run(run())


def test_the_review_is_told_that_past_story_text_never_forbids_a_spell():
    from app.agents.master.exploration import REVIEW

    # Only the world's own text decides what is allowed; the narrator's earlier flourishes are background.
    assert "Рассказ прошлых ходов не закон" in REVIEW
    assert "world_rules" in REVIEW.split("Рассказ прошлых ходов не закон")[1]


def test_an_ordinary_deed_keeps_its_remembered_note_when_the_model_intent_is_cleaned():
    from app.rules.universal.exploration import clean_model_intent

    cleaned = clean_model_intent(
        {
            "source": "mundane",
            "player_request": "ordinary",
            "effects": [{"kind": "take"}, {"kind": "free_effect", "label": "Горящая доска"}],
        }
    )
    assert [e["kind"] for e in cleaned["effects"]] == ["take", "free_effect"]


def test_the_review_does_not_demand_a_note_for_every_step_of_an_ordinary_deed():
    from app.agents.master.exploration import REVIEW

    assert "Обычному действию free_effect не нужен для каждого шага" in REVIEW


def test_the_decision_prompt_asks_for_a_short_general_ability_name():
    from app.agents.master.exploration import SYSTEM

    assert "name — короткое общее название способности" in SYSTEM


def test_the_floor_names_the_ability_generally_not_with_the_whole_request(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        unnamed = unrealisable("supernatural")
        named = dict(unrealisable("supernatural"), name="Светлячки (освещение)")
        provider = Provider(
            [
                unnamed,
                {"verdict": "pass", "covered_requirements": ["r"]},
                named,
                {"verdict": "pass", "covered_requirements": ["r"]},
                "Светлячки.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            event = (await s.scalars(select(Event))).one()
            assert event.payload["proposal"]["definition"]["name"] == "Светлячки (освещение)"
        await engine.dispose()

    asyncio.run(run())


def test_the_floor_without_any_model_name_uses_a_generic_one(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        broken = unrealisable("supernatural")
        provider = Provider([broken, {"verdict": "pass", "covered_requirements": ["r"]}, broken, "Ок.", {"verdict": "pass"}])
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            event = (await s.scalars(select(Event))).one()
            assert event.payload["proposal"]["definition"]["name"] == "Свободное заклинание"
        await engine.dispose()

    asyncio.run(run())
