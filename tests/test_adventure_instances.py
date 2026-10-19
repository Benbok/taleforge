# ruff: noqa: F811
import json

import pytest
from sqlalchemy import func, select

from app.core.authoring.contracts import InstanceOptions
from app.core.authoring.instances import instantiate_adventure
from app.core.authoring.publication import publish_project
from app.core.authoring.references import find_leaks
from app.core.authoring.validation import store_report, validate_project
from app.core.campaigns import Conflict
from app.db.models import (
    AdventureVersion,
    AuthorProject,
    Campaign,
    CampaignSecret,
    Character,
    Entity,
    GameSession,
    GeographyNode,
    LlmCall,
    Message,
    PlotAnchorBinding,
    User,
    WorldGenerationState,
)
from tests.test_authoring_validation import _prepared
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

OPTIONS = InstanceOptions(name="Игра", players=2, master={"type": "agent"})


async def published(s, pid):
    project = await s.get(AuthorProject, pid)
    await store_report(s, project, await validate_project(s, project))
    await s.commit()
    version = await publish_project(s, project, project.draft_revision, "pub")
    await s.commit()
    owner = await s.get(User, project.owner_id)
    return project, version, owner


async def entities_of(s, cid):
    return list(await s.scalars(select(Entity).where(Entity.campaign_id == cid)))


async def world_ids(s, cid):
    ents = {e.id for e in await entities_of(s, cid)}
    gens = {g.id for g in await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid))}
    return ents, gens


def test_two_launches_are_independent_and_local(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project, version, owner = await published(s, pid)
            a = await instantiate_adventure(s, owner, version, OPTIONS, "launch-a")
            b = await instantiate_adventure(
                s, owner, version, OPTIONS.model_copy(update={"name": "Вторая"}), "launch-b"
            )
            await s.commit()
            src_ents, src_gens = await world_ids(s, cid)
            a_ents, a_gens = await world_ids(s, a.campaign_id)
            b_ents, b_gens = await world_ids(s, b.campaign_id)
            assert a_ents and len(a_ents) == len(src_ents) == len(b_ents)
            assert not (a_ents & b_ents) and not (a_ents & src_ents) and not (b_ents & src_ents)
            assert not (a_gens & b_gens) and not (a_gens & src_gens)
            # предмет из A уходит, судьба NPC в A меняется; B и источник не затронуты
            in_a = await entities_of(s, a.campaign_id)
            item_a = next(e for e in in_a if (e.state or {}).get("item_ref") == "item_key")
            npc_a = next(e for e in in_a if e.kind == "creature")
            await s.delete(item_a)
            npc_a.state = {**npc_a.state, "hp": 0, "dead": True}
            await s.commit()
            for other in (b.campaign_id, cid):
                found = await entities_of(s, other)
                assert len([e for e in found if (e.state or {}).get("item_ref") == "item_key"]) == 1
                assert all(e.state.get("hp", 1) > 0 for e in found if e.kind == "creature")
            secret = await s.get(CampaignSecret, b.campaign_id)
            others = a_ents | a_gens | src_ents | src_gens | {cid, pid}
            assert not find_leaks({"plot": secret.plot, "setting": secret.setting}, others)
            rows = await s.scalars(
                select(WorldGenerationState).where(WorldGenerationState.campaign_id == b.campaign_id)
            )
            for row in rows:
                assert row.target_entity_id in b_ents and row.status == "ready" and row.lease_token is None
                assert not find_leaks({"r": row.reservation, "m": row.result_manifest}, others)
            bindings = await s.scalars(select(PlotAnchorBinding).where(PlotAnchorBinding.campaign_id == b.campaign_id))
            for binding in bindings:
                assert binding.holder_entity_id in b_ents | {None}
            nodes = await s.scalars(select(GeographyNode).where(GeographyNode.campaign_id == b.campaign_id))
            for node in nodes:
                assert node.entity_id is None or node.entity_id in b_ents
            in_b = await entities_of(s, b.campaign_id)
            for e in in_b:
                assert not find_leaks(e.state, others) and (e.location_id is None or e.location_id in b_ents)
            text = json.dumps([e.state for e in in_b], default=str)
            assert not any(i in text for i in src_ents)

    _prepared(settings, body)


def test_launch_is_a_fresh_game_with_pinned_content_and_no_prep_history(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project, version, owner = await published(s, pid)
            receipt = await instantiate_adventure(s, owner, version, OPTIONS, "k")
            await s.commit()
            game = await s.get(Campaign, receipt.campaign_id)
            workspace = await s.get(Campaign, cid)
            assert game.purpose == "game" and game.adventure_version_id == version.id
            assert game.content_chain == workspace.content_chain
            assert not (await s.scalars(select(Character).where(Character.campaign_id == game.id))).all()
            for table in (GameSession, Message, LlmCall):
                count = await s.scalar(select(func.count()).select_from(table).where(table.campaign_id == game.id))
                assert count == 0
            assert {seat.role for seat in game.seats} == {"master", "player"}
            assert game.settings["plan"]["status"] == "ready"

    _prepared(settings, body)


def test_launch_request_key_is_idempotent_and_conflicts_on_other_options(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project, version, owner = await published(s, pid)
            first = await instantiate_adventure(s, owner, version, OPTIONS, "same")
            again = await instantiate_adventure(s, owner, version, OPTIONS, "same")
            assert first.campaign_id == again.campaign_id
            with pytest.raises(Conflict):
                await instantiate_adventure(s, owner, version, OPTIONS.model_copy(update={"players": 3}), "same")
            count = await s.scalar(
                select(func.count()).select_from(Campaign).where(Campaign.launch_request_key == "same")
            )
            assert count == 1
            assert await s.scalar(select(func.count()).select_from(AdventureVersion)) == 1

    _prepared(settings, body)


def test_launch_takes_wizard_settings_and_keeps_author_intro_unless_overridden(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project, version, owner = await published(s, pid)
            wizard = InstanceOptions.model_validate(
                {
                    **OPTIONS.model_dump(),
                    "excluded_themes": ["пауки"],
                    "creation_rules": {"review": "auto"},
                    "leveling": "milestone",
                    "public_intro": "  Своя афиша  ",
                }
            )
            own = await instantiate_adventure(s, owner, version, wizard, "own", flags=("location_layouts_llm",))
            plain = await instantiate_adventure(s, owner, version, OPTIONS, "plain")
            await s.commit()
            game = await s.get(Campaign, own.campaign_id)
            assert game.public_intro == "Своя афиша"
            assert game.settings["excluded_themes"] == ["пауки"]
            assert game.settings["creation_rules"]["review"] == "auto"
            assert game.settings["leveling"] == "milestone"
            assert game.settings["location_layouts_llm"] is True
            default = await s.get(Campaign, plain.campaign_id)
            assert default.public_intro == (version.bundle["meta"].get("public_intro") or "")
            assert default.settings["creation_rules"]["review"] == "master"
            assert default.settings["excluded_themes"] == [] and default.settings["leveling"] == "xp"

    _prepared(settings, body)
