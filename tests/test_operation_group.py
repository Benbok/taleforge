"""Integration and unit tests for atomic registered operation groups runner (Task 7)."""

from __future__ import annotations

from pydantic import BaseModel

from app.tools.operation_group import CompiledCall, run_operation_group
from app.tools.registry import REGISTRY, ToolError, tool
from tests.game import import_base, party
from tests.test_tools import play


def failed_group_scenario(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    class DummyArgs(BaseModel):
        tag: str = "test"

    @tool("test_mutate_tool", "test mutate", DummyArgs)
    async def _test_mutate(ctx, args: DummyArgs):
        ctx.notices.append(("test_notice", {"tag": args.tag}, None))
        ctx.audio.append({"track": "sound.mp3"})
        ctx.signals.add("test_signal")
        ctx.outbox.append({"text": "hello"})
        ctx.operation_refs.add("prep_ref_1")
        await ctx.record("test_event", payload={"data": 1})
        return {"done": True}

    @tool("test_fail_tool", "test fail", DummyArgs)
    async def _test_fail(ctx, args: DummyArgs):
        raise ToolError("simulated tool failure", code="tool_failed")

    try:
        report = {}

        async def scenario(ctx):
            world_before = {
                "entities_count": len(ctx.world.entities),
                "game_time": ctx.world.scene.game_time,
                "focus": ctx.world.focus,
                "crew": set(ctx.world.crew),
            }
            channels_before = {
                "notices": len(ctx.notices),
                "audio": len(ctx.audio),
                "signals": set(ctx.signals),
                "outbox": len(ctx.outbox),
                "operation_refs": set(ctx.operation_refs),
                "events": len(ctx.events),
            }
            calls_used_before = ctx.resolution_calls_used

            calls = (
                CompiledCall(tool="test_mutate_tool", args={"tag": "mut"}),
                CompiledCall(tool="test_fail_tool", args={"tag": "fail"}),
            )
            res = await run_operation_group(ctx, calls)
            assert not res.ok

            world_after = {
                "entities_count": len(ctx.world.entities),
                "game_time": ctx.world.scene.game_time,
                "focus": ctx.world.focus,
                "crew": set(ctx.world.crew),
            }
            channels_after = {
                "notices": len(ctx.notices),
                "audio": len(ctx.audio),
                "signals": set(ctx.signals),
                "outbox": len(ctx.outbox),
                "operation_refs": set(ctx.operation_refs),
                "events": len(ctx.events),
            }

            report["world_before"] = world_before
            report["world_after"] = world_after
            report["channels_before"] = channels_before
            report["channels_after"] = channels_after
            report["calls_used"] = ctx.resolution_calls_used - calls_used_before
            return report

        return play(settings, cid, [], scenario)
    finally:
        REGISTRY.pop("test_mutate_tool", None)
        REGISTRY.pop("test_fail_tool", None)


def test_second_failure_restores_world_and_transient_channels(settings, client, admin):
    report = failed_group_scenario(settings, client, admin)
    assert report["world_after"] == report["world_before"]
    assert report["channels_after"] == report["channels_before"]
    assert report["calls_used"] == 2


def test_second_failure_restores_operation_refs(settings, client, admin):
    report = failed_group_scenario(settings, client, admin)
    assert "prep_ref_1" not in report["channels_after"]["operation_refs"]


def test_successful_group_commits_and_resolves_bindings(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    class SpawnArgs(BaseModel):
        name: str

    class UpdateArgs(BaseModel):
        target_id: str

    @tool("test_spawn_op", "spawn", SpawnArgs)
    async def _test_spawn(ctx, args: SpawnArgs):
        await ctx.record("spawned", payload={"name": args.name})
        return {"entity_id": "ent_999"}

    @tool("test_update_op", "update", UpdateArgs)
    async def _test_update(ctx, args: UpdateArgs):
        await ctx.record("updated", payload={"target_id": args.target_id})
        return {"updated": True}

    try:

        async def scenario(ctx):
            calls = (
                CompiledCall(tool="test_spawn_op", args={"name": "guard"}, local_binding="$guard_1"),
                CompiledCall(tool="test_update_op", args={"target_id": "$guard_1"}),
            )
            res = await run_operation_group(ctx, calls)
            assert res.ok
            assert len(res.event_ids) == 2
            assert res.bindings.get("$guard_1") == "ent_999"

        play(settings, cid, [], scenario)
    finally:
        REGISTRY.pop("test_spawn_op", None)
        REGISTRY.pop("test_update_op", None)


def test_validate_step_failure_rolls_back(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    class StepArgs(BaseModel):
        step: int

    @tool("test_step_op", "step", StepArgs)
    async def _test_step(ctx, args: StepArgs):
        await ctx.record("stepped", payload={"step": args.step})
        return {"ok": True, "result": {"step": args.step}}

    try:

        async def scenario(ctx):
            def validate(c_ctx, call, bindings):
                if call.args.get("step") == 2:
                    raise ToolError("step 2 disallowed", code="scope_denied")

            calls = (
                CompiledCall(tool="test_step_op", args={"step": 1}),
                CompiledCall(tool="test_step_op", args={"step": 2}),
            )
            res = await run_operation_group(ctx, calls, validate_step=validate)
            assert not res.ok
            assert res.error is not None
            assert res.error.code == "scope_denied"

        play(settings, cid, [], scenario)
    finally:
        REGISTRY.pop("test_step_op", None)


def test_annotate_event_customizes_metadata(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    class AnnArgs(BaseModel):
        val: int

    @tool("test_ann_op", "ann", AnnArgs)
    async def _test_ann(ctx, args: AnnArgs):
        ev = await ctx.record("annotated_event", payload={"val": args.val})
        return {"ok": True, "result": {"val": args.val}, "event_id": ev.id}

    try:

        async def scenario(ctx):
            def annotate(event, call):
                event.payload["custom_note"] = "annotated_by_runner"

            calls = (CompiledCall(tool="test_ann_op", args={"val": 42}),)
            res = await run_operation_group(ctx, calls, annotate_event=annotate)
            assert res.ok
            assert any(e.payload.get("custom_note") == "annotated_by_runner" for e in ctx.events)

        play(settings, cid, [], scenario)
    finally:
        REGISTRY.pop("test_ann_op", None)
