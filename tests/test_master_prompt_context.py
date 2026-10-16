# ruff: noqa: F811 -- shared integration fixtures
"""Role context preserves mandatory data and separates private decision knowledge."""

from app.db.models import AgentConfig, CampaignSecret
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401
from tests.test_tools import game, play  # noqa: F401


def test_narrator_view_preserves_split_and_common_knowledge(game):
    from app.agents.master.prompt_context import narration_scene
    from app.db.models import Character, Entity, Scene

    settings, cid, hero = game

    async def check(ctx):
        w = ctx.world
        from app.core.narrative.view import CampaignNarrativeView
        from tests.narrative_helpers import fact

        public = fact(value="PUBLIC_NPC_RELATIONSHIP")
        public = public.model_copy(update={"ref": public.ref.model_copy(update={"subject_id": "local"})})
        private = fact(value="PRIVATE_NPC_TRUTH", audience=(hero,))
        private = private.model_copy(
            update={"ref": private.ref.model_copy(update={"subject_id": "local", "key": "secret_truth"})}
        )
        w.narrative_view = CampaignNarrativeView({}, (public, private), ())
        w.scene = Scene(campaign_id=cid, location_id="place_a", state={}, mode="free", game_time=0, turn_order=[])
        w.entities["place_a"] = Entity(id="place_a", kind="location", name="Here", state={"layout": "PRIVATE_LAYOUT"})
        w.entities["place_b"] = Entity(id="place_b", kind="location", name="Elsewhere", state={})
        w.characters["other"] = Character(
            id="other", campaign_id=cid, name="Other hero", status="active", location_id="place_b"
        )
        for key, name, place, state in [
            ("local", "LOCAL_NPC", "place_a", {"attitude": "friendly"}),
            ("remote", "REMOTE_NPC", "place_b", {}),
            ("hidden", "SECRET_NPC", "place_a", {"secret": True}),
        ]:
            w.entities[key] = Entity(
                id=key,
                campaign_id=cid,
                kind="creature" if key == "local" else "object",
                name=name,
                state=state,
                description="",
                location_id=place,
                zone="near",
            )
        ctx.narration_viewer_ids = {hero}
        shown = narration_scene(ctx)
        assert "LOCAL_NPC" in shown
        assert "PUBLIC_NPC_RELATIONSHIP" in shown and "PRIVATE_NPC_TRUTH" in shown
        assert "REMOTE_NPC" not in shown and "SECRET_NPC" not in shown and "PRIVATE_LAYOUT" not in shown
        w.revealed[hero] = {"hidden"}
        assert "SECRET_NPC" in narration_scene(ctx)
        w.characters["other"].location_id = "place_a"
        ctx.narration_viewer_ids = {hero, "other"}
        assert "SECRET_NPC" not in narration_scene(ctx)
        assert "PUBLIC_NPC_RELATIONSHIP" in narration_scene(ctx)
        assert "PRIVATE_NPC_TRUTH" not in narration_scene(ctx)

    play(settings, cid, [], check)


def test_enabled_roles_integrate_with_refs_and_profiles(game_client, admin_g, llm, settings, monkeypatch):
    from app.agents.master import prompt_context
    from app.db.models import Campaign, LlmCall
    from tests.game import party, run
    from tests.test_master import DONE, act, rows

    original_values = prompt_context.master_prompt_values

    async def owned_values(ctx, cfg):
        assert ctx.session.in_transaction(), "Prompt DB reads must stay inside the owned narration scope"
        return await original_values(ctx, cfg)

    monkeypatch.setattr(prompt_context, "master_prompt_values", owned_values)

    c, (player,), hero = party(game_client, admin_g)

    async def enable(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {
            **campaign.settings,
            "llm_optimization": {"role_context": True, "action_refs": True, "tool_profiles": True},
        }
        await s.commit()

    run(settings, enable)
    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "wave"})]},
        DONE,
        {"text": "Ты машешь рукой."},
        {"text": "Ты машешь рукой."},
    ]
    assert act(game_client, player, c["id"], "Машу рукой")["kind"] == "narration"
    calls = rows(settings, LlmCall, LlmCall.campaign_id == c["id"], LlmCall.purpose.in_(["decide", "narrate"]))
    assert {call.diagnostics["prompt_role"] for call in calls} == {"decide", "narrate"}
    assert {call.diagnostics["prompt_version"] for call in calls} == {"context-v2"}
    assert all("role_blocks" in call.diagnostics for call in calls)


def test_parallel_narrator_and_voice_use_snapshot_after_session_closes(game, monkeypatch):
    import asyncio

    from app.agents.master import prompt_context

    settings, cid, hero = game

    async def check(ctx):
        cfg = AgentConfig(settings={})
        ctx._narration_prompt_values = await prompt_context.master_prompt_values(ctx, cfg)
        await ctx.session.close()

        async def forbidden_reads(*args, **kwargs):
            raise AssertionError("Narrator/voice reopened the closed session")

        monkeypatch.setattr(prompt_context, "master_prompt_values", forbidden_reads)
        narrator, voice = await asyncio.gather(*(
            prompt_context.build_prompt_bundle(ctx, cfg, role=role, inputs={"request": "confirmed result"})
            for role in ("narrate", "voice_line")
        ))
        assert "confirmed result" in str(narrator.messages)
        assert "confirmed result" in str(voice.messages)
        assert not ctx.session.in_transaction()
        import pytest

        with pytest.raises(AssertionError, match="reopened the closed session"):
            await prompt_context.build_prompt_bundle(ctx, cfg, role="decide", inputs={"request": "new action"})

    play(settings, cid, [], check)


def test_role_prefix_is_stable_and_private_data_stays_in_decide(game):
    from app.agents.master.prompt_context import build_prompt_bundle

    settings, cid, hero = game

    async def check(ctx):
        secret = await ctx.session.get(CampaignSecret, cid)
        if secret is None:
            secret = CampaignSecret(campaign_id=cid)
            ctx.session.add(secret)
        secret.setting = {"hidden": "SECRET_CONTEXT_SENTINEL"}
        cfg = AgentConfig(persona="Warm storyteller", settings={})
        first = await build_prompt_bundle(ctx, cfg, role="decide", inputs={"request": f"target={hero}; resource=1"})
        second = await build_prompt_bundle(ctx, cfg, role="decide", inputs={"request": "a different action"})
        assert first.messages[0] == second.messages[0]
        assert hero in str(first.messages) and "resource=1" in str(first.messages)
        assert "SECRET_CONTEXT_SENTINEL" in str(first.messages)
        narrator = await build_prompt_bundle(ctx, cfg, role="narrate", inputs={"request": "confirmed result"})
        assert "SECRET_CONTEXT_SENTINEL" not in str(narrator.messages)
        assert "вызови" not in narrator.messages[0]["content"].lower()
        assert "Warm storyteller" in str(narrator.messages)
        assert "confirmed result" in str(narrator.messages)
        import json

        print(
            "ROLE_CONTEXT_METRICS "
            + json.dumps(
                {
                    "estimate_method": "chars/4-ceil",
                    "decide": first.metadata("decide")["role_blocks"],
                    "narrate": narrator.metadata("narrate")["role_blocks"],
                }
            )
        )

    play(settings, cid, [], check)


def test_context_budget_falls_back_without_truncating_action(game):
    from app.agents.master.prompt_context import build_prompt_bundle

    settings, cid, hero = game

    async def check(ctx):
        original = [{"role": "system", "content": "legacy"}, {"role": "user", "content": "x" * 80000 + hero}]
        bundle = await build_prompt_bundle(
            ctx,
            AgentConfig(settings={}),
            role="decide",
            inputs={"request": original[1]["content"], "legacy_messages": original},
        )
        assert bundle.fallback_reason == "soft_budget"
        assert bundle.messages == original
        assert hero in bundle.messages[1]["content"]

    play(settings, cid, [], check)


def test_missing_role_input_preserves_legacy_context(game):
    from app.agents.master.prompt_context import build_prompt_bundle

    settings, cid, hero = game

    async def check(ctx):
        original = [{"role": "system", "content": hero}]
        bundle = await build_prompt_bundle(
            ctx, AgentConfig(settings={}), role="narrate", inputs={"legacy_messages": original}
        )
        assert bundle.fallback_reason == "missing_request" and bundle.messages == original
        uncertain = await build_prompt_bundle(
            ctx,
            AgentConfig(settings={}),
            role="decide",
            inputs={"request": "speech", "uncertain": True, "legacy_messages": original},
        )
        assert uncertain.fallback_reason == "uncertain_intent" and uncertain.messages == original

    play(settings, cid, [], check)


def test_decide_bundle_selects_structured_facts_by_subject(game):
    from app.agents.master.context_selection import ContextFact
    from app.agents.master.prompt_context import build_prompt_bundle

    settings, cid, hero = game

    async def check(ctx):
        facts = (
            ContextFact(
                key="npc:current",
                section="npcs",
                text="CURRENT_NPC_MARKER",
                subjects=frozenset({"npc-current"}),
                dependencies=frozenset(),
                audience=frozenset({"master"}),
            ),
            ContextFact(
                key="npc:distant",
                section="npcs",
                text="DISTANT_NPC_MARKER",
                subjects=frozenset({"npc-distant"}),
                dependencies=frozenset(),
                audience=frozenset({"master"}),
            ),
            ContextFact(
                key="action:current",
                section="actions",
                text="CURRENT_ACTION_MARKER",
                subjects=frozenset({"npc-current"}),
                dependencies=frozenset({"npc:current"}),
                audience=frozenset({"master"}),
                mandatory=True,
            ),
        )
        bundle = await build_prompt_bundle(
            ctx,
            AgentConfig(settings={}),
            role="decide",
            inputs={
                "request": "PLAYER_REQUEST",
                "context_facts": facts,
                "subjects": {"npc-current"},
            },
        )
        request = bundle.messages[1]["content"]
        assert "CURRENT_NPC_MARKER" in request
        assert "CURRENT_ACTION_MARKER" in request
        assert "DISTANT_NPC_MARKER" not in request
        assert bundle.selection_applied is True

    play(settings, cid, [], check)
