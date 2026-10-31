import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.agents.master.service import MasterService
from app.agents.master.world import ScenePreparationError
from app.core.universal.clock import clock_view
from app.db.models import Campaign, Character, Entity, Event, Message, Seat, User, WorldGenerationState
from tests.test_universal_location_knowledge import place
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def scene_plan(**overrides):
    return {
        "name": "Подземный проход",
        "description": "Под сводами сырость. На камнях остались следы колёс.",
        "objects": [
            {
                "ref": "cart",
                "kind": "object",
                "name": "Обломок повозки",
                "description": "Сухие доски в куче камней.",
                "template": "wood_source",
            },
            {
                "ref": "guard",
                "kind": "creature",
                "name": "Костяной страж",
                "description": "Страж стучит костями по камню.",
                "hostile": True,
            },
            {
                "ref": "secret",
                "kind": "object",
                "name": "PRIVATE-RELIC",
                "description": "PRIVATE-SECRET",
                "hidden": True,
            },
        ],
        "passages": [
            {
                "ref": "tunnel",
                "name": "Туннель",
                "destination": "Тёмный туннель",
                "description": "Туннель уходит в темноту.",
                "state": "open",
            }
        ],
        **overrides,
    }


def test_format_error_does_not_consume_the_only_semantic_repair_attempt(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene
        from app.db.models import LlmCall

        engine, maker = await world_setup(tmp_path)
        provider = Provider(
            [
                {},
                scene_plan(),
                {"verdict": "revise", "message": "Сохранить установленный завал."},
                scene_plan(),
                {"verdict": "pass"},
            ]
        )
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        await prepare_scene(MasterService(maker, Bus(), provider), campaign, None, "gorge")
        assert len(provider.prompts) == 5
        async with maker() as s:
            phase = await s.scalar(select(WorldGenerationState))
            assert phase.status == "ready" and phase.llm_attempt_count == 5
            calls = list(await s.scalars(select(LlmCall).where(LlmCall.generation_id == phase.id)))
            assert len(calls) == 5
            diagnostics = [c.diagnostics for c in calls if c.diagnostics]
            assert any(d.get("stage") == "validation" for d in diagnostics)
            assert any(d.get("stage") == "review" and "завал" in d.get("detail", "") for d in diagnostics)
        await engine.dispose()

    asyncio.run(run())


def test_exhausted_world_validation_keeps_diagnostic_reason_without_publishing_it(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene
        from app.core.preparation import brief_status

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        with pytest.raises(ScenePreparationError):
            await prepare_scene(MasterService(maker, Bus(), Provider([{}, {}, {}])), campaign, None, "gorge")
        async with maker() as s:
            phase = await s.scalar(select(WorldGenerationState))
            assert phase.status == "blocked"
            assert "Field required" in phase.result_manifest["detail"]
            assert "Field required" not in str(await brief_status(s, "c", phase.id))
            assert (await s.get(Entity, "gorge")).description == "Сырое ущелье."
        await engine.dispose()

    asyncio.run(run())


async def world_setup(tmp_path):
    engine, maker = await setup(tmp_path)
    await prepare(maker)
    await place(maker)
    async with maker() as s:
        c = await s.get(Campaign, "c")
        c.settings = {**c.settings, "universal_world_generation": True}
        await s.commit()
    return engine, maker


def test_scene_preparation_persists_entities_and_lazy_exits_once_without_gameplay_cost(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene

        engine, maker = await world_setup(tmp_path)
        provider = Provider([scene_plan(), {"verdict": "pass"}])
        service = MasterService(maker, Bus(), provider)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
            resources = deepcopy((await s.get(Character, "hero")).resources)
            before = await clock_view(s, "c")
        await prepare_scene(service, campaign, None, "gorge", source_id="source")
        await prepare_scene(service, campaign, None, "gorge", source_id="source")
        assert len(provider.prompts) == 2
        async with maker() as s:
            origin = await s.get(Entity, "gorge")
            assert origin.description.startswith("Сырое ущелье.")
            assert origin.state["universal_scene"]["ready"]
            assert len(origin.state["links"]) == 1
            destination = await s.get(Entity, origin.state["links"][0]["to"])
            assert not destination.state["universal_scene"]["ready"]
            assert destination.state["links"][0]["to"] == origin.id
            assert (await s.get(Character, "hero")).location_id == "gorge"
            assert (await s.get(Character, "hero")).resources == resources
            assert await clock_view(s, "c") == before
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
            jobs = list(await s.scalars(select(WorldGenerationState)))
            assert len(jobs) == 1 and jobs[0].status == "ready"
            from app.core.campaigns import Viewer
            from app.core.universal.scene import universal_scene
            from app.db.models import Seat, User

            view = await universal_scene(
                s, campaign, Viewer(await s.get(User, "u"), campaign, await s.get(Seat, "seat"))
            )
            assert "Костяной страж" in str(view)
            assert "PRIVATE" not in str(view)
        await engine.dispose()

    asyncio.run(run())


def test_world_snapshot_includes_current_public_conditions_and_evidence_only(tmp_path):
    async def run():
        from app.core.universal.world_generation import reserve_scene

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
            s.add(
                Entity(
                    id="dead",
                    campaign_id="c",
                    location_id="gorge",
                    kind="creature",
                    name="Страж",
                    description="Страж охраняет дорогу.",
                    state={"resources": {"hp": "0"}, "hostile": True},
                )
            )
            for index, (content, audience, where) in enumerate(
                [
                    ("Страж погиб у повозок.", None, "gorge"),
                    ("PRIVATE-WHISPER", ["seat"], "gorge"),
                    ("OFFSCREEN-SECRET", None, "elsewhere"),
                ],
                2,
            ):
                s.add(
                    Message(
                        campaign_id="c",
                        kind="narration",
                        seq=index,
                        content=content,
                        visible_to=audience,
                        data={"location_id": where},
                    )
                )
            hero = await s.get(Character, "hero")
            hero.sheet = {**hero.sheet, "description": {"identity": "PRIVATE-HERO-BACKGROUND"}}
            await s.flush()
            row = await reserve_scene(s, campaign, "gorge")
            context = row.reservation["context"]
            assert next(o for o in context["existing_objects"] if o["id"] == "dead")["condition"] == "dead"
            assert context["present_heroes"] == [{"id": "hero", "name": "hero", "condition": "active"}]
            assert context["established_public_evidence"] == ["Страж погиб у повозок."]
            assert "PRIVATE-HERO" not in str(context) and "OFFSCREEN" not in str(context)
        await engine.dispose()

    asyncio.run(run())


def test_player_retry_rearms_blocked_phase_with_fresh_context_and_bounded_cumulative_calls(tmp_path):
    async def run():
        from app.core.campaigns import Viewer
        from app.core.chat import retry_message
        from app.db.models import MasterTurn

        engine, maker = await world_setup(tmp_path)
        service = MasterService(maker, Bus(), Provider([{}, {}, {}]))
        tid = await service.run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            row = await s.get(WorldGenerationState, turn.trace["world_preparation_ref"])
            assert turn.status == "failed" and row.status == "blocked"
            ref = row.id
            # A previously exhausted window is a recoverable explicit player retry, too.
            row.llm_attempt_count = 6
            row.last_error = "model_budget_exhausted"
            (await s.get(Entity, "gorge")).description = "Изменённое публичное описание."
            await s.commit()
        automatic = Provider([])
        assert await MasterService(maker, Bus(), automatic).run_turn("c") == tid
        assert not automatic.prompts
        async with maker() as s:
            c = await s.get(Campaign, "c")
            await retry_message(s, Viewer(await s.get(User, "u"), c, await s.get(Seat, "seat")), "source")
            row = await s.get(WorldGenerationState, ref)
            assert row.status == "unprepared"
            assert row.reservation["foundation"] == "Изменённое публичное описание."
            assert row.reservation["model_call_limit"] == 12 and row.llm_attempt_count == 6
            await s.commit()
        provider = Provider(
            [
                scene_plan(objects=[], passages=[]),
                {"verdict": "pass"},
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="automatic",
                    effects=[dict(kind="observe")],
                ),
                "У повозок остались следы колёс.",
                {"verdict": "pass"},
            ]
        )
        assert await MasterService(maker, Bus(), provider).run_turn("c") == tid
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            row = await s.get(WorldGenerationState, ref)
            assert row.status == "ready" and row.llm_attempt_count == 8
            assert (await s.get(Entity, "gorge")).description.startswith("Изменённое публичное описание.")
            assert await s.scalar(select(func.count()).select_from(Event)) == 1
        await engine.dispose()

    asyncio.run(run())


def test_world_schema_rejects_duplicate_and_foreign_reference_shapes():
    from app.rules.universal.world import WorldScenePlan

    with pytest.raises(ValueError):
        WorldScenePlan.model_validate(
            scene_plan(
                passages=[
                    {"ref": "same", "name": "One", "destination": "A"},
                    {"ref": "same", "name": "Two", "destination": "B"},
                ]
            )
        )
    with pytest.raises(ValueError):
        WorldScenePlan.model_validate(scene_plan(objects=[{"ref": "bad", "kind": "object", "name": "Gear", "hp": 999}]))


def test_failed_provider_does_not_publish_partial_scene_and_retry_reuses_phase(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        failing = MasterService(maker, Bus(), Provider([RuntimeError("offline")]))
        with pytest.raises(ScenePreparationError):
            await prepare_scene(failing, campaign, None, "gorge", source_id="source")
        async with maker() as s:
            assert (await s.get(Entity, "gorge")).description == "Сырое ущелье."
            assert await s.scalar(select(func.count()).select_from(Entity)) == 1
            assert (await clock_view(s, "c"))["step_index"] == "0"
        recovered = MasterService(maker, Bus(), Provider([scene_plan(), {"verdict": "pass"}]))
        await prepare_scene(recovered, campaign, None, "gorge", source_id="source")
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(WorldGenerationState)) == 1
        await engine.dispose()

    asyncio.run(run())


def test_reviewed_draft_survives_a_process_crash_without_another_model_call(tmp_path, monkeypatch):
    async def run():
        from datetime import timedelta

        from app.agents.master.world import prepare_scene
        from app.core.world_generation import storage
        from app.db.models import now

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")

        class Crash(BaseException):
            pass

        original = storage.commit_session_phase

        async def crash(*args, **kwargs):
            raise Crash()

        monkeypatch.setattr(storage, "commit_session_phase", crash)
        service = MasterService(maker, Bus(), Provider([scene_plan(), {"verdict": "pass"}]))
        with pytest.raises(Crash):
            await prepare_scene(service, campaign, None, "gorge", source_id="source")
        async with maker() as s:
            row = await s.scalar(select(WorldGenerationState))
            assert row.result_manifest["reviewed_plan"]
            row.lease_until = now() - timedelta(seconds=1)
            await s.commit()
        monkeypatch.setattr(storage, "commit_session_phase", original)
        provider = Provider([])
        await prepare_scene(MasterService(maker, Bus(), provider), campaign, None, "gorge", source_id="source")
        assert not provider.prompts
        async with maker() as s:
            assert (await s.scalar(select(WorldGenerationState))).status == "ready"
        await engine.dispose()

    asyncio.run(run())


def test_concurrent_preparations_materialize_one_scene(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        provider = Provider([scene_plan(), {"verdict": "pass"}])
        services = [MasterService(maker, Bus(), provider) for _ in range(2)]
        await asyncio.gather(*(prepare_scene(s, campaign, None, "gorge", source_id="source") for s in services))
        assert len(provider.prompts) == 2
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(WorldGenerationState)) == 1
            assert len((await s.get(Entity, "gorge")).state["links"]) == 1
        await engine.dispose()

    asyncio.run(run())


def test_foreign_destinations_are_rejected_atomically(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        provider = Provider(
            [
                scene_plan(passages=[{"ref": "bad", "name": "Bad", "existing_destination_id": "foreign"}]),
                {"verdict": "pass"},
            ]
        )
        with pytest.raises(ScenePreparationError):
            await prepare_scene(MasterService(maker, Bus(), provider), campaign, None, "gorge")
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(Entity)) == 1
            assert (await s.get(Entity, "gorge")).description == "Сырое ущелье."
            assert (await s.scalar(select(WorldGenerationState))).status == "blocked"
        await engine.dispose()

    asyncio.run(run())


def test_overlong_review_message_and_destination_are_clipped_not_rejected():
    from app.rules.universal.world import WorldPassage, WorldSceneReview

    review = WorldSceneReview.model_validate({"verdict": "revise", "message": "x" * 4000})
    assert review.verdict == "revise" and len(review.message) == 1500
    passage = WorldPassage.model_validate({"ref": "tunnel", "name": "Туннель", "destination": "y" * 300})
    assert len(passage.destination) == 100


def test_a_passage_without_a_destination_hint_is_named_after_itself():
    """Found in play (2 of 3 drafts): the model left the hint out; it is cosmetic, the passage name will do."""
    from app.rules.universal.world import WorldScenePlan

    plan = WorldScenePlan.model_validate(scene_plan(passages=[{"ref": "lane", "name": "Узкий лаз"}]))
    assert plan.passages[0].destination == "Узкий лаз"
    with pytest.raises(ValueError):  # a named exit to a known place still needs no hint, an unnamed one is no exit
        WorldScenePlan.model_validate(scene_plan(passages=[{"ref": "lane", "name": ""}]))


def test_a_plan_wrapped_in_a_payload_is_unwrapped():
    """Found in play: one draft came back as {"action": ..., "payload": {the plan}}."""
    from app.rules.universal.world import WorldScenePlan

    plan = WorldScenePlan.model_validate({"action": "submit_scene", "payload": scene_plan()})
    assert plan.name == "Подземный проход"
    with pytest.raises(ValueError):  # anything else extra stays forbidden
        WorldScenePlan.model_validate({**scene_plan(), "action": "submit_scene"})


def test_a_blocked_scene_gets_a_fresh_try_on_the_next_action_within_a_bound(tmp_path):
    """Found in play: three malformed drafts blocked the opening scene for good and the game never started."""

    async def run():
        from app.agents.master.world import AUTO_RETRY_LIMIT, prepare_scene

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        with pytest.raises(ScenePreparationError):
            await prepare_scene(MasterService(maker, Bus(), Provider([{}, {}, {}])), campaign, None, "gorge")
        recovered = MasterService(maker, Bus(), Provider([scene_plan(), {"verdict": "pass"}]))
        await prepare_scene(recovered, campaign, None, "gorge")
        async with maker() as s:
            assert (await s.scalar(select(WorldGenerationState))).status == "ready"
        await engine.dispose()

        (tmp_path / "spent").mkdir()
        engine, maker = await world_setup(tmp_path / "spent")
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        with pytest.raises(ScenePreparationError):
            await prepare_scene(MasterService(maker, Bus(), Provider([{}, {}, {}])), campaign, None, "gorge")
        async with maker() as s:
            phase = await s.scalar(select(WorldGenerationState))
            phase.llm_attempt_count = AUTO_RETRY_LIMIT
            await s.commit()
        with pytest.raises(ScenePreparationError):  # the bound holds: spent attempts are not renewed by themselves
            await prepare_scene(
                MasterService(maker, Bus(), Provider([scene_plan(), {"verdict": "pass"}])), campaign, None, "gorge"
            )
        await engine.dispose()

    asyncio.run(run())


def test_a_name_with_latin_lookalikes_inside_cyrillic_is_set_right():
    """Found in play: an NPC came out as "Mapла" (Latin M, a, p inside a Cyrillic word)."""
    from app.rules.universal.world import WorldScenePlan

    plan = WorldScenePlan.model_validate(
        scene_plan(
            name="Pыбные ряды",
            objects=[{"ref": "fishwife", "kind": "npc", "name": "Mapла, торговка", "description": "Торгует рыбой."}],
            passages=[{"ref": "lane", "name": "Mocт к пристани", "destination": "Coляная пристань"}],
        )
    )
    assert plan.name == "Рыбные ряды"
    assert plan.objects[0].name == "Марла, торговка"
    assert plan.passages[0].name == "Мост к пристани" and plan.passages[0].destination == "Соляная пристань"
    # a genuinely Latin word is left alone
    assert WorldScenePlan.model_validate(scene_plan(name="Гавань Dock Nine")).name == "Гавань Dock Nine"


def test_the_scene_context_shows_the_cast_and_who_is_already_in_the_world(tmp_path):
    async def run():
        from app.core.universal.world_generation import scene_reservation
        from app.db.models import CampaignSecret

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            secret = await s.get(CampaignSecret, "c")
            secret.setting = {
                **(secret.setting or {}),
                "cast": [
                    {"name": "Годвин Тарп", "role": "цеховой старшина", "place": "кабачок"},
                    {"name": "Дорн Вельт", "role": "капитан стражи", "place": "гавань"},
                ],
            }
            s.add(
                Entity(
                    id="en_tarp",
                    campaign_id="c",
                    kind="creature",
                    location_id="gorge",
                    name="Годвин Тарп, цеховой старшина",
                    description="Грузный.",
                    state={},
                )
            )
            await s.flush()
            campaign = await s.get(Campaign, "c")
            context = (await scene_reservation(s, campaign, await s.get(Entity, "gorge")))["context"]
            assert [(p["name"], p["introduced"]) for p in context["cast"]] == [
                ("Годвин Тарп", True),
                ("Дорн Вельт", False),
            ]
            assert context["cast"][1]["place"] == "гавань"
        await engine.dispose()

    asyncio.run(run())


def test_a_person_of_the_plot_already_in_the_world_is_not_made_again_elsewhere(tmp_path):
    """Found in play: the innkeeper stood in the inn and, made again by the next scene, in the street too."""

    async def run():
        from app.agents.master.world import prepare_scene
        from app.db.models import CampaignSecret

        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            secret = await s.get(CampaignSecret, "c")
            secret.setting = {
                **(secret.setting or {}),
                "cast": [{"name": "Годвин Тарп", "role": "цеховой старшина", "place": "кабачок"}],
            }
            s.add(
                Entity(
                    id="en_tarp",
                    campaign_id="c",
                    kind="creature",
                    location_id="elsewhere",
                    name="Годвин Тарп, цеховой старшина",
                    description="Грузный.",
                    state={},
                )
            )
            campaign = await s.get(Campaign, "c")
            await s.commit()
        plan = scene_plan(
            objects=[
                {"ref": "tarp", "kind": "npc", "name": "Годвин Тарп", "description": "Опять он."},
                {"ref": "porter", "kind": "npc", "name": "Носильщик", "description": "С тачкой."},
            ]
        )
        await prepare_scene(MasterService(maker, Bus(), Provider([plan, {"verdict": "pass"}])), campaign, None, "gorge")
        async with maker() as s:
            names = [row.name for row in await s.scalars(select(Entity).where(Entity.kind == "creature"))]
            assert sum("Годвин Тарп" in name for name in names) == 1  # still only the one, where he was
            assert "Носильщик" in names  # an ordinary person of the scene is made as usual
        await engine.dispose()

    asyncio.run(run())


def test_an_object_with_a_template_or_material_outside_the_lists_is_made_ordinary_not_refused():
    """Found in play: the model wrote template values like "creature" for people; eight drafts in a row were refused
    for it and the opening trail never got prepared."""
    from app.rules.universal.world import WorldScenePlan

    plan = WorldScenePlan.model_validate(
        scene_plan(
            objects=[
                {"ref": "monk", "kind": "npc", "name": "Монах", "template": "creature", "material": "bone"},
                {"ref": "door", "kind": "object", "name": "Дверь", "template": "door", "material": "iron"},
                {"ref": "well", "kind": "object", "name": "Колодец", "template": "water_source", "material": "stone"},
            ]
        )
    )
    monk, door, well = plan.objects
    assert (monk.template, monk.material) == ("prop", "stone")
    assert (door.template, door.material) == ("prop", "stone")
    assert (well.template, well.material) == ("water_source", "stone")  # a valid value is never touched
