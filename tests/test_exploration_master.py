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
            assert list(await s.scalars(select(Event))) == []
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


def test_walking_in_bush_form_gets_the_form_reason_without_extra_model_calls(tmp_path):
    from app.core.universal.effects import start_effect
    from app.rules.universal.exploration import EffectIntentV2

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            s.add(Event(id="form", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(
                s, "c", "hero", "hero", "form", "0", EffectIntentV2(kind="change_form", lifetime="timed"), 0, 18
            )
            await s.commit()
        walking = dict(
            schema_version=2,
            source="mundane",
            player_request="ordinary",
            resolution="automatic",
            effects=[{"kind": "move"}],
        )
        provider = Provider([walking])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            message = await s.get(Message, turn.narration_message_id)
            assert "форме куста" in message.content
            assert list(await s.scalars(select(Event).where(Event.id != "form"))) == []
        assert len(provider.prompts) == 1  # a plain action needs neither a repair nor a meaning review
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
        provider = Provider([costly, review, costly, review])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        repair = json.loads(provider.prompts[2][-1]["content"])["repair"]
        assert "нужно 3" in repair and "есть 2" in repair  # the model is told the real numbers and may choose less
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert "недостаточно энергии" in message.content
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
        provider = Provider([costly, {"verdict": "pass", "covered_requirements": []}, broken, review])
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            message = await s.get(Message, (await s.get(MasterTurn, tid)).narration_message_id)
            assert "недостаточно энергии" in message.content  # not the vague "invalid parameters"
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
                "lifetime": "permanent",
                "label": "Мост",
            }
        ],
    )


def test_world_laws_reach_the_decision_and_the_review_but_never_the_private_notes(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)  # the studio is {"laws": "NO TIME TRAVEL", "private": "HIDDEN-SECRET"}
        provider = Provider(
            [
                bridge("large"),
                {"verdict": "pass", "covered_requirements": []},
                "Мост перекидывается через пропасть.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        decide, review = provider.prompts[0][-1]["content"], provider.prompts[1][-1]["content"]
        assert json.loads(decide)["world_laws"] == "NO TIME TRAVEL"
        assert "NO TIME TRAVEL" in review and "HIDDEN-SECRET" not in review
        assert "HIDDEN-SECRET" not in json.dumps(provider.prompts[2:])  # narration and its review
        await engine.dispose()

    asyncio.run(run())


def test_a_reviewer_who_finds_the_scale_implausible_stops_the_spell_and_tells_the_model_why(tmp_path):
    from app.db.models import Character

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        why = "Мост через пропасть не может быть крошечным."
        provider = Provider(
            [
                bridge("tiny"),
                {"verdict": "mismatch", "message": why},
                bridge("tiny"),
                {"verdict": "mismatch", "message": why},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        assert why in json.loads(provider.prompts[2][-1]["content"])["repair"]
        async with maker() as s:
            assert list(await s.scalars(select(Event))) == []
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "24"
            assert (await s.get(MasterTurn, tid)).status == "done"
        await engine.dispose()

    asyncio.run(run())
