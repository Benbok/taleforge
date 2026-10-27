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
